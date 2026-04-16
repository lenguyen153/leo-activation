import sys
from typing import Optional

from data_utils.logging_config import configure_logging, get_logger
from data_workers.sync.sync_segment_profiles import run_synch_profiles

configure_logging()
logger = get_logger(__name__)


def main(argv: Optional[list[str]] = None) -> None:
    argv = argv or sys.argv[1:]

    if not argv:
        raise SystemExit(
            "Usage: python sync_profile.py <segment_id>"
        )

    segment_id = argv[0]

    try:
        run_synch_profiles(segment_id=segment_id)
    except Exception as exc:
        logger.exception("Sync failed: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
