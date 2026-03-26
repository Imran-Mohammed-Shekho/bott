"""Logging configuration helpers."""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure application-wide logging."""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )

