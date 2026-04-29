"""Configuration loading, validation, and CLI argument parsing.

Handles the full configuration precedence chain:
CLI args > environment variables > .env file > defaults.
"""

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration.

    Fields:
        pega_url: Base URL of the Pega Platform instance.
        pega_username: Pega login username (required).
        pega_password: Pega login password (required).
        output_dir: Directory for all output files. Default: "output".
        headless: Run Chrome in headless mode. Default: True.
        max_retries: Max retry attempts per rule extraction. Default: 3.
        parallel_workers: Number of concurrent browser sessions. Default: 1.
        log_level: Python logging level string. Default: "INFO".
        case_type_name: Target Case Type name. Default: "Tax Compliance Training".
    """

    pega_url: str
    pega_username: str
    pega_password: str
    output_dir: str = "output"
    headless: bool = True
    max_retries: int = 3
    parallel_workers: int = 1
    log_level: str = "INFO"
    case_type_name: str = "Tax Compliance Training"

def parse_cli_args() -> Dict[str, object]:
    """Parse CLI arguments using argparse.

    Supports --url, --output-dir, --headless, --max-retries, --case-type.
    Returns a dict containing only the arguments that were explicitly provided
    by the user (omits arguments left at their default/None).
    """
    parser = argparse.ArgumentParser(
        description="Pega XML Downloader - Automated XML extraction from Pega Platform UI."
    )
    parser.add_argument(
        "--url",
        dest="pega_url",
        help="Base URL of the Pega Platform instance",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        help="Directory for output files (default: output)",
    )
    parser.add_argument(
        "--headless",
        dest="headless",
        help="Run Chrome in headless mode (true/false)",
    )
    parser.add_argument(
        "--max-retries",
        dest="max_retries",
        type=int,
        help="Max retry attempts per rule extraction (default: 3)",
    )
    parser.add_argument(
        "--case-type",
        dest="case_type_name",
        help='Name of the Case Type to open in Dev Studio (e.g. "Tax Compliance Training")',
    )

    args = parser.parse_args()

    # Build dict of only explicitly provided arguments
    result: Dict[str, object] = {}
    if args.pega_url is not None:
        result["pega_url"] = args.pega_url
    if args.output_dir is not None:
        result["output_dir"] = args.output_dir
    if args.headless is not None:
        result["headless"] = args.headless
    if args.max_retries is not None:
        result["max_retries"] = args.max_retries
    if args.case_type_name is not None:
        result["case_type_name"] = args.case_type_name

    return result


def _parse_bool(value: str) -> bool:
    """Parse a string value to boolean."""
    return value.strip().lower() in ("true", "1", "yes")


def load_config(cli_args: Optional[Dict[str, object]] = None) -> AppConfig:
    """Load configuration with precedence: CLI args > env vars > .env file > defaults.

    Loads the .env file (if present) using python-dotenv, then reads environment
    variables, and finally merges with any CLI arguments provided.

    Validates that PEGA_USERNAME and PEGA_PASSWORD are present and non-empty.
    Logs an ERROR and calls sys.exit(1) if either is missing.

    Args:
        cli_args: Optional dict of CLI-provided arguments (from parse_cli_args).

    Returns:
        A frozen AppConfig instance with all settings resolved.
    """
    # Load .env file if present (does not override existing env vars)
    load_dotenv()

    if cli_args is None:
        cli_args = {}

    # --- Resolve pega_url ---
    pega_url = cli_args.get("pega_url") or os.environ.get("PEGA_URL", "")

    # --- Resolve credentials (env vars only, no CLI override) ---
    pega_username = os.environ.get("PEGA_USERNAME", "").strip()
    pega_password = os.environ.get("PEGA_PASSWORD", "").strip()

    # Validate required credentials
    if not pega_username:
        logger.error(
            "PEGA_USERNAME is not set or empty. "
            "Please set it in your .env file or environment."
        )
        sys.exit(1)

    if not pega_password:
        logger.error(
            "PEGA_PASSWORD is not set or empty. "
            "Please set it in your .env file or environment."
        )
        sys.exit(1)

    # --- Resolve output_dir ---
    output_dir = cli_args.get("output_dir") or os.environ.get("OUTPUT_DIR", "output")

    # --- Resolve headless ---
    if "headless" in cli_args:
        headless_raw = cli_args["headless"]
        if isinstance(headless_raw, bool):
            headless = headless_raw
        else:
            headless = _parse_bool(str(headless_raw))
    elif os.environ.get("HEADLESS"):
        headless = _parse_bool(os.environ["HEADLESS"])
    else:
        headless = True

    # --- Resolve max_retries ---
    if "max_retries" in cli_args:
        max_retries = int(cli_args["max_retries"])
    elif os.environ.get("MAX_RETRIES"):
        max_retries = int(os.environ["MAX_RETRIES"])
    else:
        max_retries = 3

    # --- Resolve parallel_workers ---
    if os.environ.get("PARALLEL_WORKERS"):
        parallel_workers = int(os.environ["PARALLEL_WORKERS"])
    else:
        parallel_workers = 1

    # --- Resolve log_level ---
    if os.environ.get("LOG_LEVEL"):
        log_level = os.environ["LOG_LEVEL"].strip().upper()
    else:
        log_level = "INFO"

    # --- Resolve case_type_name ---
    if "case_type_name" in cli_args:
        case_type_name = str(cli_args["case_type_name"]).strip()
    elif os.environ.get("CASE_TYPE_NAME"):
        case_type_name = os.environ["CASE_TYPE_NAME"].strip()
    else:
        case_type_name = "Tax Compliance Training"

    if not case_type_name:
        logger.error(
            "CASE_TYPE_NAME is empty. Provide it via --case-type CLI arg or "
            "CASE_TYPE_NAME environment variable."
        )
        sys.exit(1)

    logger.debug("Resolved case_type_name='%s'", case_type_name)

    return AppConfig(
        pega_url=pega_url,
        pega_username=pega_username,
        pega_password=pega_password,
        output_dir=output_dir,
        headless=headless,
        max_retries=max_retries,
        parallel_workers=parallel_workers,
        log_level=log_level,
        case_type_name=case_type_name,
    )


def sanitize_filename(name: str) -> str:
    """Replace spaces with underscores and remove filesystem-unsafe characters.

    Keeps only alphanumeric characters, underscores, hyphens, and dots.
    Consecutive underscores are collapsed to a single underscore.

    Args:
        name: The raw name to sanitize.

    Returns:
        A filesystem-safe string suitable for use in filenames.
    """
    # Replace spaces with underscores
    result = name.replace(" ", "_")
    # Remove any character that is not alphanumeric, underscore, hyphen, or dot
    result = re.sub(r"[^\w\-.]", "", result)
    # Collapse consecutive underscores
    result = re.sub(r"_+", "_", result)
    # Strip leading/trailing underscores or dots
    result = result.strip("_.")
    return result
