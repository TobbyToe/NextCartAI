# PROJECT_PLAN.md — NextCartAI

**目标 / Goal**: 端到端 Data Engineering + ML 项目，基于 Medallion Architecture，虚拟三路数据源，最终输出一个可服务的商品推荐模型。

---

## 整体进度 / Overall Progress

```
Phase 1  Bronze — Historical    ████████████  DONE
Phase 2  Bronze — Product API   ████████████  DONE
Phase 2.5  Security Hardening   ████████████  DONE
Phase 3  Bronze — Kinesis       ░░░░░░░░░░░░  TODO
Phase 4  Silver — ETL           ░░░░░░░░░░░░  TODO
Phase 5  Gold — Features        ░░░░░░░░░░░░  TODO
Phase 6  ML — Train & Serve     ░░░░░░░░░░░░  TODO
Phase 7  CI/CD                  ░░░░░░░░░░░░  TODO
```

---

## Phase 1 ✅ — Bronze: Historical RDS → S3

**状态**: 完成

**做了什么**:
- Terraform 部署 S3 Bronze Bucket、RDS PostgreSQL (db.t3.micro)、Lambda、API Gateway
- `rds_seeder.py`：从 `references/imba_data/` 批量导入 35M 行历史订单数据到 RDS
- Terraform 部署 DMS 模块（dms.t3.small），full-load 迁移 RDS → S3

**S3 落地结果**:
```
bronze/historical/public/orders/LOAD00000001.csv.gz          (3.4M rows, 44 MB)
bronze/historical/public/order_products/LOAD00000001.csv.gz  (32M rows, 185 MB)
bronze/historical/public/order_products/LOAD00000002.csv.gz  (32M rows,  84 MB)
```

**关键 IaC 决策**:
- DMS source endpoint: `ssl_mode = "require"`（RDS 强制 SSL）
- DMS replication instance: `publicly_accessible = true`（需访问 S3）
- DMS target: `date_partition_enabled = false`（full-load 不支持日期分区）

---

## Phase 2 ✅ — Bronze: Product API → S3

**状态**: 完成

**做了什么**:
- Lambda handler 接收 `POST /product-events`，写入 `bronze/api/{type}/YYYY/MM/DD/*.json`
- `api_simulator.py`：按 `aisle → department → product` FK 顺序推送 50K 条商品目录

**S3 落地结果**:
```
bronze/api/aisle/      134  JSON files
bronze/api/department/  21  JSON files
bronze/api/product/  49688  JSON files
```

---

---

## Phase 2.5 ✅ — Security Hardening

**状态**: 完成

**做了什么**:

| 改动 | 文件 | 效果 |
|------|------|------|
| S3 VPC Gateway Endpoint | `dev/main.tf` | DMS → S3 走 AWS 私网，不经互联网；DMS 可改回 `publicly_accessible=false` |
| DMS `publicly_accessible = false` | `modules/dms/main.tf` | DMS 复制实例不再暴露公网 IP |
| API Gateway 限流 | `modules/api_gateway/main.tf` | `burst=200 / rate=100 req/s`，防止滥用 |
| API Key 认证 | `lambda_handlers/product_api/handler.py` | `x-api-key` header 校验，401 拒绝无效请求 |
| API Key 生成 + SSM 存储 | `dev/main.tf` | Terraform `random_password` 生成 32 位 key，存入 SSM SecureString |
| Lambda 注入 API Key | `modules/lambda/` | `API_KEY` 作为加密 env var 传入 Lambda |
| Simulator 发送 key header | `api_simulator.py` | Session-level `x-api-key` header，向后兼容（未设置时跳过） |
| S3 服务端加密 | `modules/s3/main.tf` | SSE-S3 (AES256) + bucket key，静态数据加密 |

**获取 API Key**:
```bash
aws ssm get-parameter \
  --name /instacart/dev/api-key \
  --with-decryption \
  --query Parameter.Value \
  --output text
```

**已知剩余风险（Prod 需解决）**:

| 风险 | 当前状态 | Prod 方案 |
|------|----------|-----------|
| 使用默认 VPC | 无网络隔离层 | 自建 VPC，private/public 子网分离 |
| RDS 本地连接需临时开公网 | 手动操作 | Bastion Host 或 SSM Session Manager 端口转发 |
| DB 密码在环境变量 | `.env` 明文 | AWS Secrets Manager |
| 无 VPC Flow Logs / CloudTrail | 无审计 | 开启并送往 CloudWatch / S3 |

---

## Phase 3 🔲 — Bronze: Kinesis Stream → S3

**目标**: 模拟实时订单事件流，落地到 `bronze/stream/`

**技术方案**:
- Terraform: `infra/modules/kinesis/` — Kinesis Data Stream + Firehose → S3
- `stream_producer.py`：从 `orders.csv` 随机采样，按时间窗口推送 JSON 事件
- Firehose 直接写入 `bronze/stream/YYYY/MM/DD/HH/*.json.gz`（无需 Lambda）

**关键字段设计** (每条事件):
```json
{
  "event_time": "2024-01-15T14:32:00Z",
  "order_id": 1234567,
  "user_id": 89012,
  "product_ids": [196, 14084, 26088],
  "source": "kinesis-stream"
}
```

**S3 目标**:
```
bronze/stream/YYYY/MM/DD/HH/*.json.gz
```

**交付物**:
- `infra/modules/kinesis/main.tf` + `variables.tf` + `outputs.tf`
- `instacart_mlops/simulators/stream_producer.py`

---

## Phase 4 🔲 — Silver: Bronze ETL (清洗标准化)

**目标**: 三路 Bronze 数据清洗、去重、标准化，写入 Silver 层

**技术方案**: AWS Glue (PySpark) 或本地 PySpark，输出 Parquet

**子任务**:

### 4-A. Historical Silver
- 输入: `bronze/historical/public/orders/*.csv.gz` + `order_products/*.csv.gz`
- 处理: 去空值、类型转换、`days_since_prior_order` null 填 0（首单）
- 输出: `silver/orders/` + `silver/order_products/`（Parquet，按 `user_id` 分区）

### 4-B. Product Silver
- 输入: `bronze/api/product/*.json` + `aisle/*.json` + `department/*.json`
- 处理: JOIN products + aisles + departments → 宽表
- 输出: `silver/products/`（Parquet，单分区）

### 4-C. Stream Silver
- 输入: `bronze/stream/*.json.gz`
- 处理: 解析 event_time、展开 product_ids 数组
- 输出: `silver/stream_events/`（Parquet，按日期分区）

**交付物**:
- `instacart_mlops/processing/bronze_to_silver.py`
- `infra/modules/glue/` (可选，或直接用本地 Spark)

---

## Phase 5 🔲 — Gold: 特征工程 (Feature Engineering)

**目标**: 从 Silver 层生成建模用宽表，输出 Gold 层

**核心宽表设计**:

### user_product_features (主表，行 = user × product)
| 字段 | 说明 |
|------|------|
| `user_id` | 用户 |
| `product_id` | 商品 |
| `order_count` | 用户购买该商品次数 |
| `reorder_rate` | 复购率 |
| `avg_cart_position` | 平均加购顺序 |
| `days_since_last_order` | 距上次购买天数 |
| `user_total_orders` | 用户总订单数 |
| `product_popularity` | 商品全局购买频率 |
| `aisle_name` | 品类（join from Silver products） |
| `department_name` | 部门 |

**输出**: `gold/user_product_features/`（Parquet，按 `user_id % 100` 分区）

**交付物**:
- `instacart_mlops/processing/silver_to_gold.py`

---

## Phase 6 🔲 — ML: 训练与推理

**目标**: 基于 Gold 层特征训练下次购买预测模型，部署推理接口

**模型**: 二分类（用户是否会再次购买某商品）
- 框架: LightGBM 或 XGBoost
- 训练数据: `gold/user_product_features/`
- 标签: `orders.eval_set == 'train'` 中的购买记录

**子任务**:
- `instacart_mlops/modeling/train.py`
  - 特征工程 + train/val split
  - 模型训练 + 评估（AUC-ROC, F1）
  - 模型序列化到 `s3://bronze/.../models/`
- `instacart_mlops/modeling/predict.py`
  - 加载模型，对 `eval_set == 'test'` 用户生成推荐列表
  - 输出: `gold/predictions/` (user_id, recommended_product_ids, scores)

**评估目标**: AUC-ROC ≥ 0.80（基于 Instacart 竞赛 baseline）

---

## Phase 7 🔲 — CI/CD: GitHub Actions

**目标**: 自动化 lint/test + 受控 Terraform 部署

**文件**:

### `.github/workflows/ci.yml`
触发: `push` / `PR`
```
flake8 instacart_mlops/
pytest tests/
```

### `.github/workflows/terraform.yml`
触发:
- PR → 自动 `terraform plan`，结果 comment 到 PR
- 手动 `workflow_dispatch` → `terraform apply`（严禁自动 apply）

认证: OIDC（不存储长期 AWS Access Key）

**子任务**:
- 创建 GitHub OIDC Provider + IAM Role（Terraform）
- 创建 S3 backend bucket for Terraform state
- 编写 `ci.yml` + `terraform.yml`
- 添加基础测试 `tests/test_seeder.py`、`tests/test_simulator.py`

---

## 技术栈总览 / Tech Stack

| 层 | 工具 |
|----|------|
| IaC | Terraform 1.6+ |
| 存储 | AWS S3 (Bronze/Silver/Gold) |
| 数据库 | AWS RDS PostgreSQL 15 |
| 迁移 | AWS DMS (full-load) |
| 流 | AWS Kinesis + Firehose |
| API | AWS API Gateway (HTTP) + Lambda (Python 3.11) |
| ETL | PySpark / AWS Glue |
| ML | LightGBM / XGBoost + scikit-learn |
| CI/CD | GitHub Actions + OIDC |
| 语言 | Python 3.11, HCL (Terraform) |

---

## 费用估算 (ap-southeast-2, Dev 环境)

| 资源 | 常驻月费 | 仅用时计费 |
|------|---------|-----------|
| S3 (~1 GB) | ~$0.03 | — |
| RDS db.t3.micro | ~$20 (停止时 $0) | 开发时启动 |
| DMS dms.t3.small | ~$39 | 仅迁移时部署，完成立删 |
| Glue DPU | ~$0.44/DPU-hr | 仅 ETL 时运行 |
| Lambda / API GW | ~$0 idle | — |
| Kinesis Firehose | ~$0.03/GB | 仅模拟时运行 |

**日常开发状态（只保留 S3）: ~$0.03/月**

---

## 里程碑 / Milestones

| # | 里程碑 | 包含 Phase |
|---|--------|-----------|
| M1 | ✅ Bronze 层完整 (两路) | Phase 1, 2 |
| M2 | Bronze 层完整 (三路) | Phase 3 |
| M3 | Silver + Gold 层完整 | Phase 4, 5 |
| M4 | 模型训练完成，AUC ≥ 0.80 | Phase 6 |
| M5 | CI/CD 上线，全流程自动化 | Phase 7 |
