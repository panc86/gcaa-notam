# NOTAM

A persistent service that downloads the daily **OMAE_ValidNOTAM** PDF from the
[GCAA UAE NOTAM page](https://www.gcaa.gov.ae/en/ais/pages/notam.aspx), parses
each NOTAM into structured fields, and saves the result as a GeoJSON
FeatureCollection. On any pipeline failure an email alert is sent automatically.

---

## How it works

The GCAA page is SharePoint-based and renders its document table (`#taskInfo`)
via a custom TreeTable. There is no static download URL — the download is
triggered by a JavaScript `onclick` handler in the Action column. A headless
Chromium browser (Playwright) is required to interact with the page.

```
Playwright (headless Chromium)
  └─ navigates to GCAA NOTAM page
  └─ waits for #taskInfo table to render
  └─ finds the row containing "OMAE_ValidNOTAM"
  └─ clicks the Action column download link
  └─ saves PDF to data/downloads/

pdfplumber + regex
  └─ extracts full text from all PDF pages
  └─ splits text into individual NOTAM blocks
  └─ parses Q / A / B / C / E lines per block
  └─ converts Q-line coord+radius → GeoJSON geometry
  └─ saves data/output/YYYYMMDD_notam.geojson

APScheduler
  └─ runs the pipeline twice daily (default 06:00 and 18:00 Asia/Dubai)
  └─ on failure: sends email alert with traceback + log file attached
```

---

## Project structure

```
notam/
├── src/notam/
│   ├── config.py        # all settings (paths, SMTP, schedule) from env
│   ├── downloader.py    # Playwright browser automation
│   ├── parser.py        # pdfplumber + regex NOTAM field extraction
│   ├── notifier.py      # async SMTP failure alert
│   └── main.py          # APScheduler persistent service entry point
├── tests/
│   ├── test_downloader.py
│   ├── test_notifier.py
│   └── test_parser.py
├── data/                # runtime artifacts (gitignored)
│   ├── downloads/       # raw PDFs
│   ├── output/          # YYYYMMDD_notam.geojson files
│   └── logs/            # daily rotating log files (notam.log)
├── .env                 # secrets and schedule config (gitignored)
└── pyproject.toml
```

---

## Requirements

- Python 3.11+
- Chromium (installed via Playwright)

---

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

---

## Configuration

Copy `.env` and fill in real values:

```ini
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user@example.com
SMTP_PASSWORD=secret
ALERT_RECIPIENT=you@example.com

# Comma-separated run hours in SCHEDULE_TZ (default: 06:00 and 18:00 Asia/Dubai)
SCHEDULE_HOURS=6,18
SCHEDULE_TZ=Asia/Dubai
```

`ALERT_RECIPIENT` is optional. If left empty, failure alerts are logged locally
but no email is sent. When set, the failure email includes the traceback in the
body and attaches the current `data/logs/notam.log` file.

---

## Running

**Start the persistent service** (runs at each hour listed in `SCHEDULE_HOURS`):

```bash
python -m notam.main
```

**Run the pipeline once manually** (useful for testing):

```python
import asyncio
from notam.main import run_pipeline
asyncio.run(run_pipeline())
```

**Parse a PDF you already have:**

```bash
python -m notam.parser data/downloads/OMAE_ValidNOTAM_20260315.pdf
```

**Debug the browser automation** (opens a visible browser window):

```python
import asyncio
from notam.downloader import download_notam
asyncio.run(download_notam(headless=False))
```

### Docker

**Build the image:**

```bash
docker build -t notam-downloader .
```

**Start the persistent service:**

```bash
docker run -d --name notam -v ./data:/app/data --env-file .env notam-downloader
```

**Run the pipeline once:**

```bash
docker run --rm -v ./data:/app/data --env-file .env notam-downloader python -c \
  "import asyncio; from notam.main import run_pipeline; asyncio.run(run_pipeline())"
```

Downloads, output, and logs are persisted to the host via the `./data` volume mount.

---

## Output format

Each run produces `data/output/YYYYMMDD_notam.geojson` — a GeoJSON FeatureCollection
where every NOTAM is a Feature:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [[...]] },
      "properties": {
        "notam_id": "A0001/26",
        "fir": "OMAE",
        "subject_code": "QRTCA",
        "condition": "IV",
        "traffic": "NBO",
        "purpose": "AE",
        "lower_fl": 0,
        "upper_fl": 45,
        "area_icao": "OMAE",
        "start_datetime": "2026-03-15T06:00:00+00:00",
        "end_datetime": "2026-03-20T00:00:00+00:00",
        "free_text": "RESTRICTED AREA ACTIVATED..."
      }
    }
  ]
}
```

**Geometry** is derived from the Q-line `COORD+RADIUS` field:
- Radius > 0 NM → `Polygon` (36-vertex circle approximation)
- Radius = 0 NM → `Point`
- No Q-line → `Point` at the OMAE FIR centroid (25.2048°N, 55.2708°E),
  with `"geometry_fallback": true` in properties

---

## NOTAM field parsing

Standard ICAO NOTAM lines extracted per block:

| Line | Content | Example |
|------|---------|---------|
| Q | FIR / subject / condition / traffic / purpose / FL range / coord+radius | `Q) OMAE/QRTCA/IV/NBO/AE/000/045/2518N05517E025` |
| A | Location ICAO code(s) | `A) OMAE` |
| B | Start datetime (YYMMDDHHmm UTC) | `B) 2603150600` |
| C | End datetime or `PERM` | `C) 2603200000` |
| E | Free text | `E) RESTRICTED AREA ACTIVATED...` |

---

## Tests

```bash
pytest
```

39 tests, no mocks, no network. The one skipped test (`test_parse_notam_pdf_real_pdf`)
requires `reportlab` to generate a real PDF fixture and is skipped when it is
not installed.

---

## Stack

| Layer | Tool |
|-------|------|
| Browser automation | [Playwright](https://playwright.dev/python/) (Chromium) |
| PDF parsing | [pdfplumber](https://github.com/jsvine/pdfplumber) |
| Field extraction | `re` (compiled at import) |
| Email alerts | [aiosmtplib](https://aiosmtplib.readthedocs.io/) + STARTTLS |
| Scheduler | [APScheduler](https://apscheduler.readthedocs.io/) 3.x async |
| Config | [python-dotenv](https://github.com/theskumar/python-dotenv) |

---

## Known limitations / risks

| Risk | Mitigation |
|------|-----------|
| SharePoint blocks headless browser | Test with `headless=False` first; add `playwright-stealth` if needed |
| Table selectors change | Row matched by text content (`has-text`), not CSS index |
| Q-line coordinate format varies | Unit-tested against multiple formats; falls back to FIR centroid |
| SMTP misconfigured | Alert errors are caught and logged; pipeline failure is still recorded locally |
