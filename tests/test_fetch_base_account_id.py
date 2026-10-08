"""Unit tests for scoring_consumer.pg_writer.fetch_base_account_id."""

from unittest.mock import MagicMock

from services.scoring_consumer.pg_writer import fetch_base_account_id


def _conn(row):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = row
    return conn, cur


def test_returns_resolved_account():
    conn, cur = _conn({"base_account_id": "999C100576"})
    assert fetch_base_account_id(conn, "p1") == "999C100576"


def test_falls_back_to_cdp_profiles_ext_data():
    conn, cur = _conn({"base_account_id": None})
    fetch_base_account_id(conn, "p1")
    sql, params = cur.execute.call_args[0]
    assert "FROM portfolios" in sql
    assert "ext_data->>'base_account_id'" in sql
    assert sql.index("FROM portfolios") < sql.index("FROM cdp_profiles")  # portfolios wins
    assert params == ("p1", "p1")


def test_returns_none_when_unresolved():
    conn, _ = _conn({"base_account_id": None})
    assert fetch_base_account_id(conn, "p1") is None
