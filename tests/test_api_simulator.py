"""Unit tests for api_simulator — no AWS or network calls required."""

from unittest.mock import MagicMock, patch

from instacart_mlops.ingestion.api_simulator import _load_records, _post_with_retry


# ── _load_records ─────────────────────────────────────────────────────────────

def test_load_records_attaches_type(tmp_path):
    csv_file = tmp_path / "aisles.csv"
    csv_file.write_text("aisle_id,aisle\n1,prepared soups salads\n2,specialty cheeses\n")

    records = _load_records("aisle", csv_file)

    assert len(records) == 2
    assert all(r["type"] == "aisle" for r in records)
    assert records[0]["aisle_id"] == "1"


def test_load_records_preserves_columns(tmp_path):
    csv_file = tmp_path / "departments.csv"
    csv_file.write_text("department_id,department\n1,frozen\n")

    records = _load_records("department", csv_file)

    assert records[0]["department"] == "frozen"
    assert records[0]["type"] == "department"


# ── _post_with_retry ──────────────────────────────────────────────────────────

def test_post_success_returns_true():
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("instacart_mlops.ingestion.api_simulator._session") as mock_session:
        mock_session.return_value.post.return_value = mock_resp
        result = _post_with_retry("http://fake", {"type": "aisle"}, delay=0)

    assert result is True


def test_post_400_returns_false_no_retry():
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "bad request"

    with patch("instacart_mlops.ingestion.api_simulator._session") as mock_session:
        mock_session.return_value.post.return_value = mock_resp
        result = _post_with_retry("http://fake", {}, delay=0, max_retries=3)

    assert result is False
    assert mock_session.return_value.post.call_count == 1  # no retry on 4xx


def test_post_retries_on_429():
    responses = [
        MagicMock(status_code=429, text="throttled"),
        MagicMock(status_code=429, text="throttled"),
        MagicMock(status_code=200),
    ]

    with patch("instacart_mlops.ingestion.api_simulator._session") as mock_session, \
         patch("time.sleep"):
        mock_session.return_value.post.side_effect = responses
        result = _post_with_retry("http://fake", {}, delay=0, max_retries=3)

    assert result is True
    assert mock_session.return_value.post.call_count == 3
