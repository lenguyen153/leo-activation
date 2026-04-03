"""WAL entry filters for CDC poller."""

from typing import Any, Dict

# Only these metricNames trigger real-time scoring.
# Everything else is left for the batch reconciliation cronjob.
CDC_METRIC_NAMES = frozenset({
    "ticker-view",
    "watchlist-add",
    "order-created",
    "order-preview",
    "order-canceled",
})


def should_publish(entry: Dict[str, Any]) -> bool:
    """
    Return True if WAL entry is a document INSERT into cdp_trackingevent
    that contains instrument_id or instrument_id_list in eventData
    AND has a whitelisted metricName.

    WAL type 2300 = document operation (insert/replace/remove).
    """
    if entry.get("type") != 2300:
        return False

    if entry.get("cname") != "cdp_trackingevent":
        return False

    data = entry.get("data", {})

    # Must be a whitelisted metricName
    if data.get("metricName") not in CDC_METRIC_NAMES:
        return False

    event_data = data.get("eventData", {})

    # Must have at least one ticker reference
    has_single = bool(event_data.get("instrument_id"))
    has_list = isinstance(event_data.get("instrument_id_list"), list) and len(event_data["instrument_id_list"]) > 0

    return has_single or has_list
