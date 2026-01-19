def main(argv: Optional[list[str]] = None) -> None:
    argv = argv or sys.argv[1:]

    if not argv:
        raise SystemExit(
            "Usage: python sync_segment_profiles.py <segment_name>"
        )

    segment_name = argv[0]

    try:
        run(segment_name)
    except Exception as exc:
        logger.exception("Sync failed: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    main()