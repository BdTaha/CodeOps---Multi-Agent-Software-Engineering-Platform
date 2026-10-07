"""Standard-library application logging without replacing server handlers."""

import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("autonomous_engineering").setLevel(level)
