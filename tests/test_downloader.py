"""Tests for notam.downloader — file-system helpers, no browser, no network."""

from datetime import date

from notam.downloader import _today_file


def test_today_file_absent(tmp_path):
    """Returns None when the downloads directory contains no PDF for today."""
    result = _today_file(downloads_dir=tmp_path)
    assert result is None


def test_today_file_present(tmp_path):
    """Returns the path when a PDF with today's date in its name exists."""
    today_str = date.today().strftime("%Y%m%d")
    pdf = tmp_path / f"OMAE_ValidNOTAM_{today_str}.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    result = _today_file(downloads_dir=tmp_path)
    assert result == pdf


def test_today_file_ignores_non_pdf(tmp_path):
    """Non-PDF files with today's date are not returned."""
    today_str = date.today().strftime("%Y%m%d")
    (tmp_path / f"OMAE_ValidNOTAM_{today_str}.txt").write_text("not a pdf")

    result = _today_file(downloads_dir=tmp_path)
    assert result is None


def test_today_file_ignores_past_date(tmp_path):
    """PDFs from a previous date are not returned."""
    (tmp_path / "OMAE_ValidNOTAM_20200101.pdf").write_bytes(b"%PDF-1.4")

    result = _today_file(downloads_dir=tmp_path)
    assert result is None


def test_today_file_creates_directory(tmp_path):
    """Creates the downloads directory if it does not yet exist."""
    new_dir = tmp_path / "downloads"
    assert not new_dir.exists()
    _today_file(downloads_dir=new_dir)
    assert new_dir.exists()
