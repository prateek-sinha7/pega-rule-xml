"""Main orchestrator module for the Pega XML Downloader.

Wires all modules together and drives the full pipeline:
config → logger → browser → auth → navigator → extractor → storage.
Handles top-level error boundaries, cleanup, and exit codes.
Supports optional parallel download mode via PARALLEL_WORKERS.
"""

import logging
import traceback
from datetime import datetime
from typing import Optional

from selenium.webdriver import Chrome

from pega_xml_downloader.auth import AuthenticationError, login
from pega_xml_downloader.browser import (
    capture_screenshot,
    create_driver,
    quit_driver,
)
from pega_xml_downloader.config import AppConfig, load_config, parse_cli_args, sanitize_filename
from pega_xml_downloader.logger import setup_logging
from pega_xml_downloader.navigator import (
    NavigationError,
    extract_case_type_xml,
    navigate_to_case_type,
)
from pega_xml_downloader.storage import LogEntry, StorageManager

logger = logging.getLogger(__name__)


def main() -> int:
    """Main entry point. Orchestrates the full pipeline.

    Steps:
    1. Load config (CLI + env + .env)
    2. Setup logging
    3. Create output directory
    4. Launch browser
    5. Authenticate
    6. Navigate to Dev Studio → Case Types → Tax Compliance Training → Actions → Open
    7. Click Actions → View XML on the opened rule page
    8. Save extracted XML to file
    9. Write execution log
    10. Cleanup and exit

    Returns:
        0 on success, 1 if extraction failed or any unhandled exception occurred.
    """
    driver: Optional[Chrome] = None
    storage: Optional[StorageManager] = None
    config: Optional[AppConfig] = None

    try:
        # --- Task 11.1: Load config, setup logging, create output dir ---
        cli_args = parse_cli_args()
        config = load_config(cli_args)

        setup_logging(config.log_level, config.output_dir)

        storage = StorageManager(config.output_dir, config.case_type_name)
        storage.ensure_output_dir()

        logger.info(
            "Pega XML Downloader starting (parallel_workers=%d)",
            config.parallel_workers,
        )

        # --- Task 11.2: Browser launch, authentication, navigation ---
        driver = create_driver(config)
        main_handle = driver.current_window_handle

        login(driver, config)

        navigate_to_case_type(driver, config.case_type_name, config.output_dir)

        # --- Step 3: Extract XML directly via Actions → View XML ---
        # After navigate_to_case_type() opens the rule-level view via
        # Actions → Open, we immediately click Actions → View XML on that
        # same page. No stage tab navigation or per-stage looping needed.
        logger.info(
            "Navigating to Case Type '%s' complete — proceeding to Actions → View XML",
            config.case_type_name,
        )

        # Build filename: {CaseTypeName}_{YYYYMMDD_HHMMSS}.xml
        extraction_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        case_type_safe = sanitize_filename(config.case_type_name)
        filename = f"{case_type_safe}_{extraction_ts}.xml"
        logger.info("Output filename: %s", filename)

        if storage.is_duplicate(filename):
            logger.info(
                "Skipping — XML for Case Type '%s' already exists as '%s'",
                config.case_type_name,
                filename,
            )
        else:
            xml_content = extract_case_type_xml(                driver, config.case_type_name, config.output_dir
            )

            if xml_content:
                try:
                    file_path = storage.save_xml(filename, xml_content)
                    storage.record_result(
                        LogEntry(
                            rule_name=config.case_type_name,
                            stage_name="CaseType",
                            output_filename=filename,
                            status="success",
                            timestamp=datetime.now().isoformat(),
                            failure_reason=None,
                        )
                    )
                    logger.info(
                        "Successfully saved XML for Case Type '%s': %s",
                        config.case_type_name,
                        file_path,
                    )
                except (IOError, OSError) as write_err:
                    logger.error(
                        "Filesystem write error for Case Type '%s': %s",
                        config.case_type_name,
                        write_err,
                    )
                    storage.record_result(
                        LogEntry(
                            rule_name=config.case_type_name,
                            stage_name="CaseType",
                            output_filename=filename,
                            status="failure",
                            timestamp=datetime.now().isoformat(),
                            failure_reason=f"Filesystem write error: {write_err}",
                        )
                    )
            else:
                capture_screenshot(
                    driver, config.output_dir, f"view_xml_{config.case_type_name}"
                )
                storage.record_result(
                    LogEntry(
                        rule_name=config.case_type_name,
                        stage_name="CaseType",
                        output_filename=filename,
                        status="failure",
                        timestamp=datetime.now().isoformat(),
                        failure_reason="extract_case_type_xml returned None",
                    )
                )
                logger.error(
                    "Failed to extract XML for Case Type '%s'",
                    config.case_type_name,
                )

        total_stages = 1  # single case type extraction

        # --- Task 11.4: Cleanup and exit ---
        storage.write_execution_log()

        summary = storage.get_summary()
        logger.info(
            "Run complete — stages: %d, total processed: %d, "
            "successful: %d, failed: %d",
            total_stages,
            summary["total_rules"],
            summary["successful"],
            summary["failed"],
        )

        quit_driver(driver)
        driver = None

        return 1 if summary["failed"] > 0 else 0

    except Exception:
        # Catch all unhandled exceptions at the main level
        logger.error(
            "Unhandled exception in main:\n%s", traceback.format_exc()
        )
        if driver is not None and config is not None:
            capture_screenshot(driver, config.output_dir, "unhandled_exception")
        return 1

    finally:
        # Ensure execution log is written and driver is quit even on early exit
        if storage is not None:
            try:
                storage.write_execution_log()
            except Exception:
                pass
        if driver is not None:
            quit_driver(driver)
