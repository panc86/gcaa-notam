"""Playwright-based downloader for OMAE_ValidNOTAM PDF from the GCAA UAE NOTAM page.

The page is a SharePoint site with a custom TreeTable (#taskInfo). Each row has an
Action column with View and Download links.  The Download link calls a JS function
``downloadNotamFile(filename)`` which creates a temporary ``<a>`` element and
programmatically clicks it to trigger a browser download.
"""

import asyncio
import logging
from datetime import date
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Download, Locator, Page, async_playwright

from notam import config

logger = logging.getLogger(__name__)

# Table that lists NOTAM PDF files.
_TABLE_SELECTOR = "#taskInfo"


def _today_file(downloads_dir: Path | None = None) -> Path | None:
    """Return path to today's already-downloaded PDF if it exists, else None."""
    d = downloads_dir or config.DOWNLOADS_DIR
    d.mkdir(exist_ok=True)
    today_str = date.today().strftime("%Y%m%d")
    for f in d.iterdir():
        if today_str in f.name and f.suffix.lower() == ".pdf":
            logger.info("Today's file already exists: %s", f)
            return f
    return None


async def _open_browser(pw: object, headless: bool) -> tuple[Browser, Page]:
    """Launch Chromium and open a new page configured for file downloads.

    Args:
        pw: Playwright instance from async_playwright context manager.
        headless: Whether to run Chromium in headless mode.

    Returns:
        Tuple of (browser, page).
    """
    browser: Browser = await pw.chromium.launch(headless=headless)
    context: BrowserContext = await browser.new_context(accept_downloads=True)
    page: Page = await context.new_page()
    return browser, page


async def _load_notam_page(page: Page) -> None:
    """Navigate to the GCAA NOTAM page and wait for the table to render.

    Args:
        page: Playwright page object.

    Raises:
        TimeoutError: If the page or table does not load in time.
    """
    logger.info("Navigating to NOTAM page: %s", config.NOTAM_PAGE_URL)
    await page.goto(config.NOTAM_PAGE_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_selector(f"{_TABLE_SELECTOR} tbody tr", timeout=30_000)
    logger.info("Table loaded")


async def _find_notam_row(page: Page) -> Locator:
    """Locate the table row whose title contains the configured SEARCH_TERM.

    Args:
        page: Playwright page after the table has loaded.

    Returns:
        Locator for the first matching row.

    Raises:
        RuntimeError: If no matching row is found.
    """
    row = page.locator(f"{_TABLE_SELECTOR} tbody tr", has_text=config.SEARCH_TERM).first
    if await row.count() == 0:
        raise RuntimeError(
            f"No table row containing '{config.SEARCH_TERM}' found."
        )
    logger.info("Found row: %s", await row.locator("td.file-Title").text_content())
    return row


async def _download_pdf(page: Page, row: Locator, downloads_dir: Path) -> Path:
    """Click the download icon in the Action column and save the PDF.

    The download link triggers ``downloadNotamFile(filename)`` via its ``onclick``
    handler, which creates a temporary ``<a download=...>`` and clicks it.
    Playwright captures this as a standard download event.

    Args:
        page: Playwright page (needed to listen for the download event).
        row: Locator for the matching table row.
        downloads_dir: Directory where the PDF will be saved.

    Returns:
        Path to the saved PDF file.
    """
    download_link = row.locator("a[title='Download']")
    async with page.expect_download(timeout=30_000) as dl_info:
        await download_link.click()

    download: Download = await dl_info.value
    suggested = download.suggested_filename or f"OMAE_ValidNOTAM_{date.today():%Y%m%d}.pdf"
    dest = downloads_dir / suggested
    await download.save_as(dest)
    logger.info("Saved PDF to %s", dest)
    return dest


async def download_notam(
    headless: bool = True,
    downloads_dir: Path | None = None,
) -> Path:
    """Download the OMAE_ValidNOTAM PDF for today.

    Skips the download and returns the existing path if today's file is already present.

    Args:
        headless: Whether to run Chromium in headless mode.
        downloads_dir: Override for the downloads directory (default: config.DOWNLOADS_DIR).

    Returns:
        Path to the saved (or already-existing) PDF.

    Raises:
        RuntimeError: If the matching table row is not found.
        TimeoutError: If any page interaction exceeds its timeout.
    """
    d = downloads_dir or config.DOWNLOADS_DIR
    existing = _today_file(d)
    if existing:
        return existing

    d.mkdir(exist_ok=True)

    async with async_playwright() as pw:
        browser, page = await _open_browser(pw, headless)
        try:
            await _load_notam_page(page)
            row = await _find_notam_row(page)
            return await _download_pdf(page, row, d)
        finally:
            await browser.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = asyncio.run(download_notam(headless=False))
    print(f"Downloaded: {path}")
