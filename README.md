# Pega XML Downloader

Automated extraction of rule XML definitions from the Pega Platform UI using Selenium WebDriver. The tool drives a Chrome browser session through Pega Dev Studio, systematically discovering and downloading XML for every rule across all configured stages of a target Case Type.

## Prerequisites

- **Python 3.10+**
- **Google Chrome** (latest stable version)
- **ChromeDriver** matching your installed Chrome version ([download](https://chromedriver.chromium.org/downloads))

Ensure `chromedriver` is available on your system PATH or in the project directory.

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd pega-xml-downloader

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Pega credentials and settings
```

## Configuration

### Environment Variables

All configuration can be set via a `.env` file or environment variables. CLI arguments take precedence over environment variables.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PEGA_URL` | Yes | — | Base URL of the Pega Platform instance (e.g., `https://pega.example.com/prweb`) |
| `PEGA_USERNAME` | Yes | — | Pega login username |
| `PEGA_PASSWORD` | Yes | — | Pega login password |
| `OUTPUT_DIR` | No | `output` | Directory where XML files, logs, and screenshots are saved |
| `HEADLESS` | No | `true` | Run Chrome in headless mode (`true`/`false`) |
| `MAX_RETRIES` | No | `3` | Maximum retry attempts per rule extraction before marking as failed |
| `STAGE_LIST` | No | `Initialization,Primary,Alternatives` | Comma-separated list of Case Type stages to process (in order) |
| `PARALLEL_WORKERS` | No | `1` | Number of concurrent browser sessions (`1` = sequential) |
| `LOG_LEVEL` | No | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |

### CLI Arguments

| Argument | Overrides | Description |
|----------|-----------|-------------|
| `--url` | `PEGA_URL` | Base URL of the Pega Platform instance |
| `--output-dir` | `OUTPUT_DIR` | Directory for output files |
| `--headless` | `HEADLESS` | Run Chrome in headless mode (`true`/`false`) |
| `--max-retries` | `MAX_RETRIES` | Max retry attempts per rule extraction |
| `--stages` | `STAGE_LIST` | Comma-separated list of stages to process |

### Configuration Precedence

Settings are resolved in the following order (highest priority first):

1. CLI arguments
2. Environment variables
3. `.env` file
4. Built-in defaults

## Usage

### Basic Usage

Run with settings from your `.env` file:

```bash
python -m pega_xml_downloader
```

### With CLI Overrides

Override specific settings via command-line arguments:

```bash
python -m pega_xml_downloader --url https://pega.example.com --output-dir ./xml_output --stages "Initialization,Primary"
```

### Headless Mode Disabled (for debugging)

```bash
python -m pega_xml_downloader --headless false
```

## Output Structure

All output is written to the configured output directory (default: `output/`):

```
output/
├── Tax_Compliance_Training_Initialization_Program_Design.xml
├── Tax_Compliance_Training_Initialization_Another_Rule.xml
├── Tax_Compliance_Training_Primary_Some_Flow.xml
├── Tax_Compliance_Training_Alternatives_Alt_Rule.xml
├── FAILED_Tax_Compliance_Training_Primary_Broken_Rule_20240115T143022.png
├── execution_log.jsonl
└── downloader.log
```

| File | Description |
|------|-------------|
| `*.xml` | Extracted rule XML files, named `{CaseType}_{Stage}_{RuleName}.xml` |
| `FAILED_*.png` | Screenshots captured on extraction failure (for diagnostics) |
| `execution_log.jsonl` | Structured log with one JSON object per rule processed (status, timestamps, errors) |
| `downloader.log` | Full application log with timestamps, levels, and module names |

### Execution Log Format

Each line in `execution_log.jsonl` is a self-contained JSON object:

```json
{"rule_name": "Program Design", "stage_name": "Initialization", "output_filename": "Tax_Compliance_Training_Initialization_Program_Design.xml", "status": "success", "timestamp": "2024-01-15T14:30:22.123456", "failure_reason": null}
```

## Features

- **Idempotent re-runs**: Skips already-downloaded rules based on filesystem and in-memory tracking
- **Retry with exponential backoff**: Failed extractions are retried up to `MAX_RETRIES` times (2s, 4s, 8s... max 30s)
- **Screenshot on failure**: Captures browser state when extraction fails for post-run diagnostics
- **Structured execution log**: JSON Lines format for easy parsing and auditing
- **Optional parallelism**: Multiple browser sessions via `PARALLEL_WORKERS` for faster processing
- **Headless operation**: Runs without a visible browser window by default
