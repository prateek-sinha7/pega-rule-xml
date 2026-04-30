# Pega XML Downloader

A Python automation script that logs into the Pega Platform UI using Selenium, navigates to specified Case Types in Dev Studio, and downloads XML definitions for both the Case Type and all its stage flows via **Actions → View XML**.

## How It Works

The script follows the exact same steps a developer would take manually:

1. Login to Pega
2. Switch to Dev Studio (via workspace switcher)
3. Navigate to Case Types (inside Developer iframe)
4. For each Case Type:
   a. Click the Case Type → **Actions → Open**
   b. Click **Actions → View XML** (saves Case Type XML)
   c. Click the **Stages** tab
   d. For each flow (e.g., Program Design, Training Execution):
      - Click the flow to select it
      - Click **Actions → View XML** (saves flow XML)
   e. Navigate back to Case Types list for the next one

All XML files are organized into per-Case-Type folders.

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
| `CASE_TYPE_NAMES` | No | `Tax Compliance Training` | Comma-separated list of Case Type names to download |
| `CASE_TYPE_NAME` | No | — | Single Case Type name (backwards-compatible, use `CASE_TYPE_NAMES` for multiple) |
| `OUTPUT_DIR` | No | `output` | Root directory where per-Case-Type folders and logs are saved |
| `HEADLESS` | No | `true` | Run Chrome without a visible window (`true`/`false`) |
| `MAX_RETRIES` | No | `3` | Retry attempts before marking an extraction as failed |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### CLI Arguments

| Argument | Overrides | Description |
|---|---|---|
| `--url` | `PEGA_URL` | Pega login page URL |
| `--case-type` | `CASE_TYPE_NAMES` | Comma-separated Case Type names (e.g., `"Tax Filing,Tax Calculation"`) |
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

### Download multiple Case Types

```bash
python -m pega_xml_downloader --case-type "Tax Compliance Training,Tax Cost Allocation,Tax Filing"
```

Or set in `.env`:

```
CASE_TYPE_NAMES=Tax Compliance Training,Tax Cost Allocation,Tax Filing
```

### Full example with all overrides

```bash
python -m pega_xml_downloader \
  --url "https://your-pega-instance.com/prweb/app/default/..." \
  --case-type "Tax Compliance Training,Tax Cost Allocation" \
  --output-dir ./downloads \
  --headless false
```

### Debug mode — verbose logging

```bash
LOG_LEVEL=DEBUG python -m pega_xml_downloader --headless false
```

---

## Output

Each Case Type gets its own folder under `OUTPUT_DIR`. The Case Type XML and all stage flow XMLs are saved inside it:

```
output/
├── Tax_Compliance_Training/
│   ├── Tax_Compliance_Training_20260430_104615.xml          ← Case Type XML
│   ├── Tax_Compliance_Training_Program_Design_20260430_104622.xml    ← flow XML
│   ├── Tax_Compliance_Training_Training_Execution_20260430_104625.xml
│   ├── Tax_Compliance_Training_Competency_Assessment_20260430_104628.xml
│   ├── Tax_Compliance_Training_Compliance_Reporting_20260430_104631.xml
│   ├── Tax_Compliance_Training_Remediation_Path_20260430_104634.xml
│   └── Tax_Compliance_Training_Approval_Rejection_20260430_104637.xml
├── Tax_Cost_Allocation/
│   ├── Tax_Cost_Allocation_20260430_104700.xml
│   ├── Tax_Cost_Allocation_Data_Collection_20260430_104705.xml
│   └── ...
├── execution_log.jsonl       ← structured result log
└── downloader.log            ← full run log
```

### XML filename format

- Case Type: `{CaseTypeName}_{YYYYMMDD_HHMMSS}.xml`
- Stage flow: `{CaseTypeName}_{FlowName}_{YYYYMMDD_HHMMSS}.xml`

Each run produces uniquely timestamped files — previous downloads are never overwritten.

### Execution log format

`execution_log.jsonl` contains one JSON object per extraction:

```json
{"rule_name": "Tax Compliance Training", "stage_name": "CaseType", "output_filename": "Tax_Compliance_Training_20260430_104615.xml", "status": "success", "timestamp": "2026-04-30T10:46:15.000000", "failure_reason": null}
{"rule_name": "Tax Compliance Training > Program Design", "stage_name": "StageFlow", "output_filename": "Tax_Compliance_Training_Program_Design_20260430_104622.xml", "status": "success", "timestamp": "2026-04-30T10:46:22.000000", "failure_reason": null}
```

---

## How the Pega Navigation Works

The script handles Pega's complex iframe-based UI:

1. **Login** → lands in App Studio
2. **Workspace switch** → `pega.desktop.wks.switchWorkspace("Developer")` switches to Dev Studio
3. **Developer iframe** → all Dev Studio content is inside `iframe#Developer`
4. **Case Types tab** → accordion tab with `role="tab"` and `title="Case Types"` (CSS transform requires JS click)
5. **Case Type link** → `a.explorer_primary` in the tree grid
6. **PegaGadget iframes** → each Case Type editor loads in a new `PegaGadget{N}Ifr` iframe
7. **Actions → Open** → opens the Case Type rule in another new PegaGadget iframe
8. **Stages tab** → `<DIV class="header">Stages</DIV>` accordion header
9. **Flow names** → `<input name*="ppyStageName">` elements with flow names as values
10. **Actions → View XML** → dropdown menu items found via JavaScript (XPath can't match nested spans)

---

## Cross-Platform Notes

- Works on both **macOS** and **Windows**
- On macOS, "View XML" typically opens in a **popup window** — the script closes it after extraction
- On Windows (headless), "View XML" may render **inline** — the script extracts from `page_source` without navigation
- File paths use `os.path.join()` for cross-platform compatibility

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Activate your virtual environment first |
| Login fails | Check `PEGA_USERNAME` / `PEGA_PASSWORD` in `.env` |
| Case Type not found | Verify the name matches exactly as shown in Pega Dev Studio |
| XML popup timeout | Run with `--headless false` to watch the browser |
| Empty XML file | Check `downloader.log` — the popup may have loaded in an unexpected iframe |
| Screenshot saved but no XML | The `FAILED_*.png` shows the browser state at the point of failure |
| "no such window" error | The browser window was closed unexpectedly — check if View XML rendered inline |
| Stage flows not downloading | Check that the Stages tab is accessible and flow names are visible |

---

## Project Structure

```
pega-rule-xml/
├── pega_xml_downloader/
│   ├── __init__.py
│   ├── __main__.py       # Entry point: python -m pega_xml_downloader
│   ├── main.py           # Orchestrator — processes each Case Type + stage flows
│   ├── config.py         # Configuration loading + CLI parsing
│   ├── auth.py           # Pega login
│   ├── browser.py        # Chrome WebDriver setup + popup handling
│   ├── navigator.py      # Dev Studio navigation + XML extraction + stage flows
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
