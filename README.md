# Pega XML Downloader

A Python automation script that logs into the Pega Platform UI using Selenium, navigates to a specified Case Type in Dev Studio, and downloads its XML definition via **Actions → Open → Actions → View XML**.

## How It Works

The script follows the exact same steps a developer would take manually:

1. Login to Pega
2. Switch to Dev Studio
3. Navigate to Case Types
4. Locate the target Case Type
5. Click **Actions → Open**
6. Click **Actions → View XML**
7. Extract the XML from the popup window
8. Save it as `{CaseTypeName}_{YYYYMMDD_HHMMSS}.xml`

---

## Prerequisites

- **Python 3.10+**
- **Google Chrome** (latest stable)
- **ChromeDriver** is managed automatically by Selenium 4.6+ — no manual download needed

---

## Installation

```bash
# Clone the repository
git clone https://github.com/prateek-sinha7/pega-rule-xml.git
cd pega-rule-xml

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Set up your environment file
cp .env.example .env
# Edit .env with your Pega credentials and settings
```

---

## Configuration

All settings can be provided via `.env` file, environment variables, or CLI arguments.

**Precedence (highest to lowest):** CLI args → environment variables → `.env` file → defaults

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `PEGA_URL` | Yes | — | Full URL of the Pega login page |
| `PEGA_USERNAME` | Yes | — | Pega login username |
| `PEGA_PASSWORD` | Yes | — | Pega login password |
| `CASE_TYPE_NAME` | No | `Tax Compliance Training` | Name of the Case Type to open in Dev Studio |
| `OUTPUT_DIR` | No | `output` | Directory where XML files, logs, and screenshots are saved |
| `HEADLESS` | No | `true` | Run Chrome without a visible window (`true`/`false`) |
| `MAX_RETRIES` | No | `3` | Retry attempts before marking an extraction as failed |
| `PARALLEL_WORKERS` | No | `1` | Number of concurrent browser sessions (keep at `1` for stability) |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### CLI Arguments

| Argument | Overrides | Description |
|---|---|---|
| `--url` | `PEGA_URL` | Pega login page URL |
| `--case-type` | `CASE_TYPE_NAME` | Case Type name to download |
| `--output-dir` | `OUTPUT_DIR` | Output directory path |
| `--headless` | `HEADLESS` | Headless mode (`true`/`false`) |
| `--max-retries` | `MAX_RETRIES` | Max retry attempts |

---

## Usage

### Basic — uses settings from `.env`

```bash
python -m pega_xml_downloader
```

### With browser visible (recommended for first run / debugging)

```bash
python -m pega_xml_downloader --headless false
```

### Target a different Case Type

```bash
python -m pega_xml_downloader --case-type "My Other Case Type"
```

### Full example with all overrides

```bash
python -m pega_xml_downloader \
  --url https://your-pega-instance.com/prweb \
  --case-type "Tax Compliance Training" \
  --output-dir ./downloads \
  --headless false
```

### Debug mode — verbose logging

```bash
LOG_LEVEL=DEBUG python -m pega_xml_downloader --headless false
```

---

## Output

All files are written to `OUTPUT_DIR` (default: `~/Downloads/`):

```
~/Downloads/
├── Tax_Compliance_Training_20260429_162741.xml   ← downloaded XML
├── Tax_Cost_Allocation_20260429_163012.xml
├── Tax_Data_Collection_20260429_163245.xml
├── FAILED_view_xml_timeout_..._20260429T163000.png  ← screenshot on failure
├── execution_log.jsonl                           ← structured result log
└── downloader.log                                ← full run log
```

### XML filename format

```
{CaseTypeName}_{YYYYMMDD_HHMMSS}.xml
```

Example: `Tax_Compliance_Training_20260429_162741.xml`

Each run produces a new uniquely timestamped file — previous downloads are never overwritten.

### Execution log format

`execution_log.jsonl` contains one JSON object per run:

```json
{"rule_name": "Tax Compliance Training", "stage_name": "CaseType", "output_filename": "Tax_Compliance_Training_20260429_162741.xml", "status": "success", "timestamp": "2026-04-29T16:27:41.506000", "failure_reason": null}
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Run `source venv_mac/bin/activate` first |
| Login fails | Check `PEGA_USERNAME` / `PEGA_PASSWORD` in `.env` |
| Case Type not found | Verify `CASE_TYPE_NAME` matches exactly what appears in the Pega UI |
| XML popup timeout | Run with `--headless false` to watch the browser and identify the issue |
| Empty XML file | Check `downloader.log` — the popup may have loaded in an unexpected iframe |
| Screenshot saved but no XML | The `FAILED_*.png` shows the browser state at the point of failure |

---

## Project Structure

```
pega-rule-xml/
├── pega_xml_downloader/
│   ├── __init__.py
│   ├── __main__.py       # Entry point: python -m pega_xml_downloader
│   ├── main.py           # Orchestrator
│   ├── config.py         # Configuration loading + CLI parsing
│   ├── auth.py           # Pega login
│   ├── browser.py        # Chrome WebDriver setup
│   ├── navigator.py      # Dev Studio navigation + XML extraction
│   ├── storage.py        # File I/O + execution log
│   └── logger.py         # Logging setup
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Requirements

```
selenium==4.27.1
python-dotenv==1.0.1
```

Install with:

```bash
pip install -r requirements.txt
```
