"""Email failure alerts for the NOTAM pipeline.

Sends an SMTP email (STARTTLS) containing the exception traceback and
the current log file as an attachment.  Errors during sending are logged
locally but never re-raised so that a broken SMTP config cannot mask
the original failure.
"""

import logging
import traceback
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib

from notam import config

logger = logging.getLogger(__name__)


def _build_alert_message(
    error: Exception,
    log_file: Path | None,
    today: date,
) -> MIMEMultipart:
    """Build the failure alert email without sending it.

    Args:
        error: The exception that triggered the alert.
        log_file: Path to the current log file (attached if present).
        today: Date used in the email subject and body.

    Returns:
        A ready-to-send MIMEMultipart message.
    """
    tb_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    body = (
        f"NOTAM pipeline failure on {today:%Y-%m-%d}\n"
        f"{'=' * 60}\n\n"
        f"Error type:  {type(error).__name__}\n"
        f"Message:     {error}\n\n"
        f"Traceback:\n{tb_str}\n"
        f"{'=' * 60}\n\n"
        f"Log file attached: {log_file.name if log_file else '(none)'}\n"
    )
    msg = MIMEMultipart()
    msg["From"] = config.SMTP_USER
    msg["To"] = config.ALERT_RECIPIENT
    msg["Subject"] = f"[NOTAM] Download failure \u2013 {today:%Y-%m-%d}"
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if log_file and log_file.exists():
        log_text = log_file.read_text(encoding="utf-8", errors="replace")
        attachment = MIMEText(log_text, "plain", "utf-8")
        attachment.add_header("Content-Disposition", "attachment", filename=log_file.name)
        msg.attach(attachment)

    return msg


async def send_failure_alert(error: Exception, log_file: Path | None = None) -> None:
    """Send an email alert; silently no-ops when ALERT_RECIPIENT is not configured.

    Args:
        error: The exception that triggered the alert.
        log_file: Optional path to the log file to attach.
    """
    if not config.ALERT_RECIPIENT:
        logger.warning("ALERT_RECIPIENT not configured; skipping email alert")
        return

    msg = _build_alert_message(error, log_file, date.today())
    try:
        await aiosmtplib.send(
            msg,
            hostname=config.SMTP_HOST,
            port=config.SMTP_PORT,
            username=config.SMTP_USER,
            password=config.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info("Failure alert sent to %s", config.ALERT_RECIPIENT)
    except (aiosmtplib.SMTPException, OSError) as smtp_err:
        logger.error("Failed to send alert email: %s", smtp_err)
