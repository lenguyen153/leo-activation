"""Transform WAL entries into CdpEventMessage objects (fan-out by ticker)."""

import logging
from typing import Any, Dict, List

from services.shared.schemas import CdpEventMessage
from services.cdc_poller.metric_cache import get_metric_score

logger = logging.getLogger(__name__)

MAX_TICKERS_PER_EVENT = 20


def transform(entry: Dict[str, Any]) -> List[CdpEventMessage]:
    """
    Fan-out a single WAL entry into one CdpEventMessage per ticker.
    Caps at MAX_TICKERS_PER_EVENT to prevent abuse.
    """
    data = entry.get("data", {})
    event_data = data.get("eventData", {})

    # Extract tickers
    single = event_data.get("instrument_id")
    id_list = event_data.get("instrument_id_list", [])

    if single:
        tickers = [single]
    elif isinstance(id_list, list):
        tickers = [t for t in id_list if t]
    else:
        return []

    # Cap to prevent fan-out abuse
    tickers = tickers[:MAX_TICKERS_PER_EVENT]

    event_key = data.get("_key", "")
    fingerprint_id = data.get("fingerprintId", "")
    metric_name = data.get("metricName", "")
    created_at = data.get("createdAt", "")
    metric_score = get_metric_score(metric_name)

    if not fingerprint_id:
        logger.warning("WAL entry %s has no fingerprintId, skipping", event_key)
        return []

    messages = []
    for ticker in tickers:
        ticker = str(ticker).strip()
        if not ticker:
            continue
        messages.append(
            CdpEventMessage(
                event_key=event_key,
                fingerprint_id=fingerprint_id,
                metric_name=metric_name,
                ticker=ticker,
                metric_score=metric_score,
                created_at=created_at,
            )
        )

    return messages
