"""NOTAM downloader persistent service.

Runs twice daily (default 06:00 and 18:00 Asia/Dubai) via APScheduler.
All output is written to a daily log file; on failure the log file is
attached to an email alert.
"""

import asyncio
import contextlib
import logging
import logging.handlers
from datetime import date
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from notam import config
from notam.downloader import download_notam
from notam.notifier import send_failure_alert
from notam.parser import parse_notam_pdf, save_geojson

# ---------------------------------------------------------------------------
# Logging — console + daily rotating file in data/logs/
# ---------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _setup_logging() -> None:
    """Configure root logger with console and daily rotating file handlers."""
    config.LOGS_DIR.mkdir(exist_ok=True)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        config.LOGS_DIR / "notam.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logging.basicConfig(
        level=logging.INFO,
        format=_LOG_FORMAT,
        handlers=[logging.StreamHandler(), file_handler],
    )


def _current_log_file() -> Path:
    """Return the path to the active log file."""
    return config.LOGS_DIR / "notam.log"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


async def run_pipeline() -> None:
    """Download today's NOTAM PDF, parse it, and save as GeoJSON.

    On failure, sends an email alert with the exception details and the
    current log file, then re-raises the exception.
    """
    logger.info("Pipeline started for %s", date.today())
    try:
        pdf_path = await download_notam()
        feature_collection = parse_notam_pdf(pdf_path)
        out_path = save_geojson(feature_collection, date.today())
        logger.info("Pipeline complete. Output: %s", out_path)
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc)
        await send_failure_alert(exc, _current_log_file())
        raise


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_forever() -> None:
    """Start the scheduler and block until interrupted."""
    scheduler = AsyncIOScheduler(timezone=config.SCHEDULE_TZ)
    for hour in config.SCHEDULE_HOURS:
        scheduler.add_job(
            run_pipeline,
            trigger="cron",
            hour=hour,
            id=f"notam_{hour:02d}",
            replace_existing=True,
            misfire_grace_time=3600,
        )
    scheduler.start()
    logger.info(
        "Scheduler started. Daily runs at %s %s",
        ", ".join(f"{h:02d}:00" for h in config.SCHEDULE_HOURS),
        config.SCHEDULE_TZ,
    )
    try:
        await asyncio.Event().wait()
    finally:
        logger.info("Shutting down scheduler")
        scheduler.shutdown()


def main() -> None:
    """Entry point for ``python -m notam.main``."""
    _setup_logging()
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(_run_forever())


if __name__ == "__main__":
    main()
