import json
import os
import uuid
from datetime import datetime, timezone

import boto3

s3 = boto3.client("s3")
BUCKET = os.environ["BRONZE_BUCKET"]
API_KEY = os.environ.get("API_KEY", "")

VALID_TYPES = {"product", "aisle", "department"}


def lambda_handler(event, context):
    try:
        # API key check — skip only if API_KEY env var is unset (local/test)
        if API_KEY:
            headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
            if headers.get("x-api-key") != API_KEY:
                return _response(401, {"error": "Unauthorized"})

        body = json.loads(event.get("body") or "{}")
        event_type = body.get("type")

        if event_type not in VALID_TYPES:
            return _response(400, {"error": f"'type' must be one of {sorted(VALID_TYPES)}"})

        key = _s3_key(event_type)
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(body),
            ContentType="application/json",
        )
        return _response(200, {"status": "ok", "s3_key": key})

    except json.JSONDecodeError:
        return _response(400, {"error": "request body must be valid JSON"})
    except Exception as e:
        return _response(500, {"error": str(e)})


def _s3_key(event_type: str) -> str:
    now = datetime.now(timezone.utc)
    return (
        f"bronze/api/{event_type}/"
        f"{now.year}/{now.month:02d}/{now.day:02d}/"
        f"{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    )


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
