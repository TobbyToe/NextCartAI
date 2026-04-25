"""
Simulate product metadata events by POSTing aisles, departments, and products
to the deployed API Gateway endpoint.

Send order: aisles → departments → products (products reference both FKs).
Each row is written to s3://bronze/api/<type>/YYYY/MM/DD/<timestamp>.json
by the Lambda handler.

Usage:
    export API_ENDPOINT=https://<id>.execute-api.ap-southeast-2.amazonaws.com//product-events
    export API_KEY=$(aws ssm get-parameter --name /instacart/dev/api-key --with-decryption --query Parameter.Value --output text)
    python -m instacart_mlops.ingestion.api_simulator
    python -m instacart_mlops.ingestion.api_simulator --workers 20 --delay 0.005
"""

import argparse
import csv
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock, local

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

IMBA_DIR = Path(__file__).parents[2] / "references" / "imba_data"
API_KEY = os.environ.get("API_KEY", "")

# Send aisles and departments before products (products FK-reference both)
SOURCES = [
    ("aisle",       IMBA_DIR / "aisles.csv"),
    ("department",  IMBA_DIR / "departments.csv"),
    ("product",     IMBA_DIR / "products.csv"),
]

_thread_local = local()


def _session() -> requests.Session:
    """One persistent Session per thread for connection reuse."""
    if not hasattr(_thread_local, "session"):
        sess = requests.Session()
        if API_KEY:
            sess.headers.update({"x-api-key": API_KEY})
        _thread_local.session = sess
    return _thread_local.session


def _post_with_retry(
    endpoint: str,
    payload: dict,
    delay: float,
    max_retries: int = 3,
) -> bool:
    """POST payload to endpoint. Retries on 429/5xx with exponential backoff."""
    time.sleep(delay)
    for attempt in range(max_retries):
        try:
            resp = _session().post(endpoint, json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            if resp.status_code in (429, 503):
                wait = 2 ** attempt
                log.warning(f"Throttled ({resp.status_code}), retrying in {wait}s …")
                time.sleep(wait)
            else:
                log.error(f"Unexpected {resp.status_code}: {resp.text[:120]}")
                return False
        except requests.RequestException as exc:
            wait = 2 ** attempt
            log.warning(f"Request error ({exc}), retrying in {wait}s …")
            time.sleep(wait)
    return False


def _load_records(event_type: str, filepath: Path) -> list[dict]:
    """Read CSV and attach the event type field expected by the Lambda handler."""
    with open(filepath, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        row["type"] = event_type
    return rows


def _send_batch(
    records: list[dict],
    event_type: str,
    endpoint: str,
    workers: int,
    delay: float,
) -> tuple[int, int]:
    """Submit records via thread pool. Returns (success_count, failure_count)."""
    total = len(records)
    success = 0
    failure = 0
    lock = Lock()

    def _task(payload: dict) -> bool:
        return _post_with_retry(endpoint, payload, delay)

    log.info(f"Sending {total:,} {event_type} records with {workers} workers …")
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_task, rec): rec for rec in records}
        for i, future in enumerate(as_completed(futures), start=1):
            with lock:
                if future.result():
                    success += 1
                else:
                    failure += 1
            if i % 100 == 0 or i == total:
                elapsed = time.perf_counter() - t0
                rate = i / elapsed
                log.info(
                    f"  [{event_type}] {i:>6,}/{total:,} sent  "
                    f"✓ {success:,}  ✗ {failure}  "
                    f"({rate:.0f} req/s)"
                )

    return success, failure


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate product API events.")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("API_ENDPOINT", ""),
        help="API Gateway endpoint URL (or set API_ENDPOINT env var).",
    )
    parser.add_argument(
        "--workers", type=int, default=10,
        help="Number of concurrent threads (default: 10).",
    )
    parser.add_argument(
        "--delay", type=float, default=0.01,
        help="Per-request sleep in seconds to pace traffic (default: 0.01).",
    )
    args = parser.parse_args()

    if not args.endpoint:
        raise SystemExit("API_ENDPOINT is not set. Pass --endpoint or export API_ENDPOINT.")

    total_success = 0
    total_failure = 0

    for event_type, filepath in SOURCES:
        if not filepath.exists():
            log.warning(f"{filepath} not found — skipping {event_type}.")
            continue

        records = _load_records(event_type, filepath)
        ok, fail = _send_batch(records, event_type, args.endpoint, args.workers, args.delay)
        total_success += ok
        total_failure += fail
        log.info(f"{event_type} complete: {ok:,} ok / {fail} failed.")

    log.info(
        f"All done — {total_success:,} records sent, {total_failure} failures."
    )


if __name__ == "__main__":
    main()
