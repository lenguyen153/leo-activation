import logging
import os
import sys
from typing import Optional

# ensure project root on path for imports used by tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_workers.sync_segment_profiles import run_synch_profiles
logger = logging.getLogger(__name__)


def main(argv: Optional[list[str]] = None) -> None:
    argv = argv or sys.argv[1:]

    if not argv:
        raise SystemExit(
            "Usage: python sync_segment_profiles.py <segment_id>"
        )

    segment_id = argv[0]

    try:
        run_synch_profiles(segment_id=segment_id)
    except Exception as exc:
        logger.exception("Sync failed: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    main()