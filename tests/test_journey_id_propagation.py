"""journey_id flows WAL entry → CdpEventMessage → ScoreUpdateMessage → forwarder payload."""

from unittest.mock import patch

from services.cdc_poller.transformer import transform
from services.shared.schemas import CdpEventMessage, ScoreUpdateMessage
from services.ws_forwarder.consumer import scrub_pii

SOCIAL = "5BtTqEwmZTyUqLfemqGIJ2"


def _wal_entry(**data):
    return {
        "type": 2300,
        "cname": "cdp_trackingevent",
        "data": {
            "_key": "k1",
            "fingerprintId": "fp1",
            "metricName": "ticker-view",
            "createdAt": "2026-10-08T06:30:00Z",
            "eventData": {"instrument_id": "FPT"},
            **data,
        },
    }


@patch("services.cdc_poller.transformer.get_metric_score", return_value=1.0)
def test_journey_id_reaches_forwarder_payload(_):
    [event] = transform(_wal_entry(refJourneyId=SOCIAL))
    assert event.journey_id == SOCIAL

    # Round-trip through Kafka serialisation, as the scoring consumer does
    event = CdpEventMessage.model_validate_json(event.model_dump_json())
    update = ScoreUpdateMessage(
        tenant_id="t", profile_id="p", base_account_id="999C100576",
        ticker=event.ticker, metric_name=event.metric_name,
        interest_score=0.5, raw_score=1.0, updated_at="2026-10-08T06:30:01Z",
        event_data=event.event_data, journey_id=event.journey_id,
    )
    assert scrub_pii(update.model_dump())["journey_id"] == SOCIAL


@patch("services.cdc_poller.transformer.get_metric_score", return_value=1.0)
def test_missing_ref_journey_id_defaults_to_empty(_):
    [event] = transform(_wal_entry())
    assert event.journey_id == ""


def test_old_messages_without_journey_id_still_parse():
    old_event = '{"event_key":"k","fingerprint_id":"f","metric_name":"m","ticker":"FPT","created_at":"x"}'
    assert CdpEventMessage.model_validate_json(old_event).journey_id == ""

    old_update = '{"tenant_id":"t","profile_id":"p","ticker":"FPT","interest_score":0,"raw_score":0,"updated_at":"x"}'
    assert ScoreUpdateMessage.model_validate_json(old_update).journey_id == ""
