# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 1. 核心目标 / Project Goal

构建一个基于 **Medallion Architecture** 的端到端 Data Engineering & ML 项目，虚拟三个数据源（Kinesis Stream、Product API、历史 RDS 数据），利用 Terraform 实施 IaC，并通过 GitHub Actions 进行受控部署。

Build an end-to-end Data Engineering & ML project based on **Medallion Architecture**, simulating three data sources (Kinesis Stream, Product API, Historical RDS), using Terraform for IaC and GitHub Actions for controlled deployment.

---

## 2. 目录结构 / Directory Structure

```plaintext
├── Makefile                        <- make tf-plan / tf-apply / lint / test
├── pyproject.toml                  <- 工具配置统一入口 / Unified tool config (black, flake8, pytest)
├── requirements.txt                <- Python 依赖 / Python dependencies
├── .env.example                    <- 环境变量模板（不提交真实值）/ Env vars template (no real values committed)
│
├── references/                     <- 项目参考资料（只读）/ Project reference materials (read-only)
│   ├── data_samples/               <- 原始 CSV / gz 样本文件（5-6 张表）/ Raw CSV/gz sample files
│   ├── diagrams/                   <- ER 图、整体架构图 / ER diagram, architecture diagram
│   └── presentation/               <- 项目 PPT / Project presentation
│
├── data/                           <- 本地测试数据（不提交大文件）/ Local test data (no large files committed)
│   ├── raw/                        <- 原始不可变数据 / Original immutable data
│   └── interim/                    <- 中间层数据 / Intermediate data
│
├── infra/                          <- 全部 Terraform 代码 / All Terraform code
│   ├── modules/                    <- 可复用模块 / Reusable modules
│   │   ├── s3/
│   │   ├── rds/
│   │   ├── dms/
│   │   ├── kinesis/
│   │   ├── lambda/
│   │   └── api_gateway/
│   ├── lambda_handlers/            <- Lambda 函数源码（与 Terraform 同目录便于打包）
│   │   └── product_api/
│   │       └── handler.py          <- 接收 product/aisle/department 事件，写入 bronze/api/
│   ├── environments/               <- 环境隔离 / Environment isolation
│   │   ├── dev/                    <- Terraform 根目录（在此运行 terraform init/plan/apply）
│   │   └── prod/
│   └── main.tf                     <- 入口说明 / Entry point instructions
│
├── notebooks/                      <- EDA 与实验（命名规范：1.0-tg-description）/ EDA and experiments
│
├── instacart_mlops/                <- 核心 Python 包 / Core Python package
│   ├── config.py                   <- AWS ARN、Bucket Names、环境变量读取 / AWS config and env vars
│   │
│   ├── simulators/                 <- 【虚拟数据源】仅用于开发和测试 / Mock data sources (dev/test only)
│   │   ├── stream_producer.py      <- 模拟 Kinesis Stream 事件推送 / Mock Kinesis stream event producer
│   │   ├── api_simulator.py        <- 模拟 Product API 响应 / Mock Product API responses
│   │   └── rds_seeder.py           <- 用 CSV 样本初始化 RDS 历史数据 / Seed RDS with historical CSV data
│   │
│   ├── ingestion/                  <- 读取真实/虚拟数据源，写入 Bronze 层 / Read sources, write to Bronze
│   │   ├── kinesis_consumer.py     <- 消费 Kinesis Stream → s3://bronze/stream/
│   │   ├── api_poller.py           <- 拉取 Product API → s3://bronze/api/
│   │   └── rds_extractor.py        <- 抽取 RDS 历史表 → s3://bronze/historical/
│   │
│   ├── processing/                 <- Glue/Spark ETL，Bronze → Silver → Gold
│   │   ├── bronze_to_silver.py     <- 清洗、标准化、去重
│   │   └── silver_to_gold.py       <- 聚合、特征工程，输出建模用宽表
│   │
│   └── modeling/                   <- 模型训练与推理 / Model training and inference
│       ├── train.py
│       └── predict.py
│
└── .github/workflows/              <- CI/CD 流水线 / CI/CD pipelines
    ├── ci.yml                      <- lint + test，每次 push/PR 自动触发 / Auto on push/PR
    └── terraform.yml               <- plan 自动 + apply 手动触发 / Plan auto, apply manual
```

---

## 3. 数据源与 Simulator 说明 / Data Sources & Simulators

项目虚拟三个数据源，`simulators/` 负责在本地或 CI 中生成假数据，`ingestion/` 负责以统一方式消费它们。

The project simulates three data sources. `simulators/` generates fake data for local/CI use; `ingestion/` consumes them uniformly.

| 数据源 / Source | 模拟方式 / Simulator | 摄取目标 / Ingestion Target |
|---|---|---|
| Kinesis Stream | `stream_producer.py` 推送 JSON 事件 | `s3://bronze/stream/` |
| Product API | `api_simulator.py` 启动本地 mock server | `s3://bronze/api/` |
| Historical RDS | `rds_seeder.py` 从 `references/data_samples/` 导入 CSV | `s3://bronze/historical/` |

---

## 4. 基础设施原则 / Infrastructure Strategy

- **工具 / Tooling**: 使用 Terraform（非 CDK），所有模块放 `infra/modules/`，环境差异放 `infra/environments/`。Use Terraform (not CDK); modules under `infra/modules/`, env differences under `infra/environments/`.
- **权限 / Permissions**: GitHub Actions 使用 OIDC 认证，禁止在仓库中存储长期有效的 AWS Access Keys。GitHub Actions authenticates via OIDC — no long-lived AWS keys in the repo.
- **状态管理 / State**: Terraform state 存储在 S3 backend，按环境隔离。Terraform state stored in S3 backend, isolated per environment.

---

## 5. CI/CD 策略 / CI/CD Strategy

| 触发条件 / Trigger | 行为 / Action |
|---|---|
| Push / PR | 自动运行 flake8 + pytest / Auto-run flake8 + pytest |
| PR | `terraform plan` 自动执行并评论结果 / Auto-run and post plan output as PR comment |
| 手动 / Manual (`workflow_dispatch`) | `terraform apply` — 严禁自动部署 / Must be manually triggered, never auto-deployed |

---

## 6. 开发规范 / Development Standards

- **数据流 / Data Flow**: 严格遵循 ELT。数据原样落 `s3://.../bronze/`，禁止在 `ingestion/` 阶段做清洗。Strict ELT — raw data lands in `bronze/` as-is; no transformation in `ingestion/`.
- **Medallion 分层**: `bronze/` 原始 → `silver/` 清洗标准化 → `gold/` 聚合宽表。`bronze/` raw → `silver/` cleaned → `gold/` aggregated feature tables.
- **代码风格 / Code Style**: PEP 8，配置统一在 `pyproject.toml`。PEP 8; all tool config in `pyproject.toml`.
- **references/ 只读**: 该目录仅存放文档和样本，不在任何代码中 import 或写入。`references/` is read-only documentation; never import from or write to it in code.
