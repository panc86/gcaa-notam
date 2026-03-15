"""Tests for notam.notifier — message construction and no-op guard."""

import asyncio
from datetime import date

from notam.notifier import _build_alert_message, send_failure_alert

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(msg) -> str:
    """Decode the (possibly base64-encoded) text body of a MIMEMultipart message."""
    part = msg.get_payload()[0]
    raw = part.get_payload(decode=True)
    return raw.decode("utf-8") if isinstance(raw, bytes) else raw


def _attachment(msg) -> str | None:
    """Return the decoded text of the first attachment, or None if absent."""
    parts = msg.get_payload()
    if len(parts) < 2:
        return None
    raw = parts[1].get_payload(decode=True)
    return raw.decode("utf-8") if isinstance(raw, bytes) else raw


# ---------------------------------------------------------------------------
# _build_alert_message — pure function, no I/O
# ---------------------------------------------------------------------------


def test_subject_contains_date():
    msg = _build_alert_message(ValueError("boom"), None, date(2026, 3, 15))
    assert "2026-03-15" in msg["Subject"]


def test_subject_contains_notam_label():
    msg = _build_alert_message(RuntimeError("x"), None, date(2026, 3, 15))
    assert "NOTAM" in msg["Subject"]


def test_body_contains_error_type():
    msg = _build_alert_message(ValueError("test error"), None, date(2026, 3, 15))
    assert "ValueError" in _body(msg)


def test_body_contains_error_message():
    msg = _build_alert_message(ValueError("something went wrong"), None, date(2026, 3, 15))
    assert "something went wrong" in _body(msg)


def test_body_contains_traceback():
    try:
        raise TypeError("trace me")
    except TypeError as exc:
        error = exc

    msg = _build_alert_message(error, None, date(2026, 3, 15))
    body = _body(msg)
    assert "TypeError" in body
    assert "trace me" in body


def test_body_mentions_log_filename(tmp_path):
    log_file = tmp_path / "notam.log"
    log_file.write_text("some log content")
    msg = _build_alert_message(RuntimeError("err"), log_file, date(2026, 3, 15))
    assert "notam.log" in _body(msg)


def test_body_shows_none_when_no_log_file():
    msg = _build_alert_message(RuntimeError("err"), None, date(2026, 3, 15))
    assert "(none)" in _body(msg)


# ---------------------------------------------------------------------------
# Log file attachment
# ---------------------------------------------------------------------------


def test_log_file_attached(tmp_path):
    log_file = tmp_path / "notam.log"
    log_file.write_text("line one\nline two\n")
    msg = _build_alert_message(RuntimeError("err"), log_file, date(2026, 3, 15))
    text = _attachment(msg)
    assert text is not None
    assert "line one" in text
    assert "line two" in text


def test_log_file_attachment_filename(tmp_path):
    log_file = tmp_path / "notam.log"
    log_file.write_text("content")
    msg = _build_alert_message(RuntimeError("err"), log_file, date(2026, 3, 15))
    disposition = msg.get_payload()[1]["Content-Disposition"]
    assert "notam.log" in disposition


def test_no_attachment_when_log_file_is_none():
    msg = _build_alert_message(RuntimeError("err"), None, date(2026, 3, 15))
    assert _attachment(msg) is None


def test_no_attachment_when_log_file_missing(tmp_path):
    missing = tmp_path / "does_not_exist.log"
    msg = _build_alert_message(RuntimeError("err"), missing, date(2026, 3, 15))
    assert _attachment(msg) is None


# ---------------------------------------------------------------------------
# send_failure_alert — no-op when ALERT_RECIPIENT is not configured
# ---------------------------------------------------------------------------


def test_send_failure_alert_no_recipient(monkeypatch):
    """When ALERT_RECIPIENT is empty the function returns without error."""
    import notam.config as cfg

    monkeypatch.setattr(cfg, "ALERT_RECIPIENT", "")
    asyncio.run(send_failure_alert(RuntimeError("test"), None))
