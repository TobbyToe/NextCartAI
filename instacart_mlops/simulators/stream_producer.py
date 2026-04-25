"""
Simulate real-time order events by pushing sampled records to Kinesis.

Reads orders from references/imba_data/orders.csv, constructs a JSON event
per order, and sends them to a Kinesis Data Stream. Firehose then delivers
the records to s3://bronze/stream/YYYY/MM/DD/HH/*.json.gz automatically.

Event schema:
    {
        "event_id":               "uuid4",
        "event_time":             "2024-01-15T14:32:00Z",
        "order_id":               int,
        "user_id":                int,
        "order_dow":              int,   # 0=Saturday, 1=Sunday, …
        "order_hour_of_day":      int,
        "days_since_prior_order": float | null,
        "source":                 "kinesis-simulator"
    }

Usage:
    export AWS_DEFAULT_REGION=ap-southeast-2
    export KINESIS_STREAM_NAME=instacart-stream-dev
    python -m instacart_mlops.simulators.stream_producer
    python -m instacart_mlops.simulators.stream_producer --count 500 --rate 20
"""

import argparse
import csv
import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ORDERS_CSV = Path(__file__).parents[2] / "references" / "imba_data" / "orders.csv"

# Kinesis put_records limit: 500 records or 5 MB per call
_BATCH_SIZE = 500


def _load_orders(sample_size: int) -> list[dict]:
    """Reservoir-sample `sample_size` rows from orders.csv without loading all."""
    reservoir: list[dict] = []
    with open(ORDERS_CSV, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            if len(reservoir) < sample_size:
                reservoir.append(row)
            else:
                j = random.randint(0, i)
                if j < sample_size:
                    reservoir[j] = row
    random.shuffle(reservoir)
    return reservoir


def _to_event(row: dict) -> dict:
    """Convert a CSV row to a Kinesis event payload."""
    prior = row.get("days_since_prior_order", "")
    return {
        "event_id": uuid.uuid4().hex,
        "event_time": datetime.now(timezone.utc).isoformat(),
        "order_id": int(row["order_id"]),
        "user_id": int(row["user_id"]),
        "order_dow": int(row["order_dow"]),
        "order_hour_of_day": int(row["order_hour_of_day"]),
        "days_since_prior_order": float(prior) if prior else None,
        "source": "kinesis-simulator",
    }


def _put_batch(client, stream_name: str, events: list[dict]) -> tuple[int, int]:
    """Send a batch via put_records. Returns (success, failed)."""
    records = [
        {"Data": json.dumps(e).encode(), "PartitionKey": str(e["user_id"])}
        for e in events
    ]
    try:
        resp = client.put_records(StreamName=stream_name, Records=records)
        failed = resp.get("FailedRecordCount", 0)
        return len(records) - failed, failed
    except ClientError as exc:
        log.error(f"put_records error: {exc}")
        return 0, len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Push simulated order events to Kinesis.")
    parser.add_argument(
        "--stream",
        default=os.environ.get("KINESIS_STREAM_NAME", ""),
        help="Kinesis stream name (or set KINESIS_STREAM_NAME env var).",
    )
    parser.add_argument(
        "--count", type=int, default=1000,
        help="Total number of events to send (default: 1000).",
    )
    parser.add_argument(
        "--rate", type=float, default=10.0,
        help="Target events per second (default: 10).",
    )
    args = parser.parse_args()

    if not args.stream:
        raise SystemExit(
            "Stream name not set. Pass --stream or export KINESIS_STREAM_NAME."
        )
    if not ORDERS_CSV.exists():
        raise SystemExit(f"Orders file not found: {ORDERS_CSV}")

    log.info(f"Sampling {args.count} orders from {ORDERS_CSV.name} …")
    orders = _load_orders(args.count)
    log.info(f"Loaded {len(orders)} orders. Pushing to '{args.stream}' at {args.rate} ev/s …")

    client = boto3.client("kinesis")
    delay = 1.0 / args.rate  # seconds between events

    total_ok = 0
    total_fail = 0
    t0 = time.perf_counter()

    for batch_start in range(0, len(orders), _BATCH_SIZE):
        batch = orders[batch_start: batch_start + _BATCH_SIZE]
        events = [_to_event(row) for row in batch]
        ok, fail = _put_batch(client, args.stream, events)
        total_ok += ok
        total_fail += fail

        sent = batch_start + len(batch)
        elapsed = time.perf_counter() - t0
        log.info(
            f"  [{sent:>6,}/{len(orders):,}]  "
            f"✓ {total_ok:,}  ✗ {total_fail}  "
            f"({sent / elapsed:.1f} ev/s)"
        )

        # Pace remaining batches to stay near target rate
        batch_time = len(batch) * delay
        actual = time.perf_counter() - t0 - (batch_start * delay)
        if batch_time > actual:
            time.sleep(batch_time - actual)

    log.info(f"Done — {total_ok:,} sent, {total_fail} failed.")


if __name__ == "__main__":
    main()
