"""Centralised configuration loaded from environment / .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root is three levels above this file: src/notam/config.py → notam/
PROJECT_ROOT: Path = Path(__file__).parents[2]

# DATA_DIR can be overridden via env var (e.g. in Docker where the wheel is
# installed into site-packages and PROJECT_ROOT no longer points at the repo).
DATA_DIR: Path = Path(os.getenv("NOTAM_DATA_DIR", str(PROJECT_ROOT / "data")))

DOWNLOADS_DIR: Path = DATA_DIR / "downloads"
OUTPUT_DIR: Path = DATA_DIR / "output"
LOGS_DIR: Path = DATA_DIR / "logs"

# NOTAM page
NOTAM_PAGE_URL: str = "https://www.gcaa.gov.ae/en/ais/pages/notam.aspx"
SEARCH_TERM: str = "OMAE_ValidNOTAM"

# SMTP / alerts
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.example.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
ALERT_RECIPIENT: str = os.getenv("ALERT_RECIPIENT", "")

# Scheduler — comma-separated hours, e.g. "6,18" for 06:00 and 18:00
SCHEDULE_HOURS: list[int] = [
    int(h.strip()) for h in os.getenv("SCHEDULE_HOURS", "6,18").split(",")
]
SCHEDULE_TZ: str = os.getenv("SCHEDULE_TZ", "Asia/Dubai")
