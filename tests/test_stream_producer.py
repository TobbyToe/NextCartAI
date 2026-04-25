"""Unit tests for stream_producer — no AWS calls required."""

import json
from unittest.mock import MagicMock

from instacart_mlops.simulators.stream_producer import _put_batch, _to_event


# ── _to_event ─────────────────────────────────────────────────────────────────

def test_to_event_required_fields():
    row = {
        "order_id": "1", "user_id": "42",
        "order_dow": "3", "order_hour_of_day": "14",
        "days_since_prior_order": "7.0",
    }
    event = _to_event(row)
    assert event["order_id"] == 1
    assert event["user_id"] == 42
    assert event["days_since_prior_order"] == 7.0
    assert event["source"] == "kinesis-simulator"
    assert "event_id" in event
    assert "event_time" in event


def test_to_event_null_prior_order():
    row = {
        "order_id": "1", "user_id": "1",
        "order_dow": "0", "order_hour_of_day": "8",
        "days_since_prior_order": "",
    }
    event = _to_event(row)
    assert event["days_since_prior_order"] is None


def test_to_event_unique_ids():
    row = {
        "order_id": "1", "user_id": "1",
        "order_dow": "0", "order_hour_of_day": "8",
        "days_since_prior_order": "",
    }
    ids = {_to_event(row)["event_id"] for _ in range(10)}
    assert len(ids) == 10


# ── _put_batch ────────────────────────────────────────────────────────────────

def test_put_batch_success():
    events = [_to_event({
        "order_id": str(i), "user_id": "1",
        "order_dow": "1", "order_hour_of_day": "9",
        "days_since_prior_order": "",
    }) for i in range(3)]

    mock_client = MagicMock()
    mock_client.put_records.return_value = {"FailedRecordCount": 0, "Records": []}

    ok, fail = _put_batch(mock_client, "test-stream", events)

    assert ok == 3
    assert fail == 0
    call_args = mock_client.put_records.call_args
    assert call_args.kwargs["StreamName"] == "test-stream"
    assert len(call_args.kwargs["Records"]) == 3


def test_put_batch_partial_failure():
    events = [_to_event({
        "order_id": "1", "user_id": "1",
        "order_dow": "1", "order_hour_of_day": "9",
        "days_since_prior_order": "",
    }) for _ in range(4)]

    mock_client = MagicMock()
    mock_client.put_records.return_value = {"FailedRecordCount": 1, "Records": []}

    ok, fail = _put_batch(mock_client, "test-stream", events)

    assert ok == 3
    assert fail == 1


def test_put_batch_records_are_valid_json():
    event = _to_event({
        "order_id": "99", "user_id": "7",
        "order_dow": "2", "order_hour_of_day": "11",
        "days_since_prior_order": "3.5",
    })
    mock_client = MagicMock()
    mock_client.put_records.return_value = {"FailedRecordCount": 0, "Records": []}

    _put_batch(mock_client, "test-stream", [event])

    record_data = mock_client.put_records.call_args.kwargs["Records"][0]["Data"]
    parsed = json.loads(record_data.decode())
    assert parsed["order_id"] == 99
