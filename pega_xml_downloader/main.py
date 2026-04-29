"""Main orchestrator module for the Pega XML Downloader.

Wires all modules together and drives the full pipeline:
config → logger → browser → auth → navigator → extractor → storage.
Handles top-level error boundaries, cleanup, and exit codes.
Supports optional parallel download mode via PARALLEL_WORKERS.
"""

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional

from selenium.webdriver import Chrome

from pega_xml_downloader.auth import AuthenticationError, login
from pega_xml_downloader.browser import (
    capture_screenshot,
    create_driver,
    quit_driver,
)
from pega_xml_downloader.config import AppConfig, load_config, parse_cli_args
from pega_xml_downloader.extractor import ExtractionResult, extract_rule_xml
from pega_xml_downloader.logger import setup_logging
from pega_xml_downloader.navigator import (
    NavigationError,
    RuleRef,
    discover_rules,
    discover_stages,
    extract_stage_xml,
    navigate_to_case_type,
)
from pega_xml_downloader.storage import LogEntry, StorageManager

logger = logging.getLogger(__name__)


def _process_rule_worker(
    rule_ref: RuleRef,
    config: AppConfig,
    storage: StorageManager,
) -> None:
    """Process a single rule in a parallel worker thread.

    Each worker creates its own browser session, authenticates, navigates
    to the Case Type, extracts the rule's XML, and cleans up.

    Args:
        rule_ref: Reference to the rule to process.
        config: Application configuration.
        storage: Shared StorageManager instance (thread-safe).
    """
    driver: Optional[Chrome] = None
    try:
        filename = storage.build_filename(rule_ref.stage_name, rule_ref.name)

        # Double-check duplicate (another worker may have processed it)
        if storage.is_duplicate(filename):
            logger.info(
                "[Worker] Skipping duplicate rule '%s' (file '%s' already exists)",
                rule_ref.name,
                filename,
            )
            return

        # Create a dedicated browser session for this worker
        driver = create_driver(config)
        main_handle = driver.current_window_handle

        # Authenticate
        login(driver, config)

        # Navigate to Case Type
        navigate_to_case_type(driver, config.case_type_name, config.output_dir)

        # Extract XML
        result: ExtractionResult = extract_rule_xml(
            driver,
            rule_ref,
            config.max_retries,
            main_handle,
        )

        if result.success:
            try:
                file_path = storage.save_xml(filename, result.xml_content)
                storage.record_result(
                    LogEntry(
                        rule_name=rule_ref.name,
                        stage_name=rule_ref.stage_name,
                        output_filename=filename,
                        status="success",
                        timestamp=datetime.now().isoformat(),
                        failure_reason=None,
                    )
                )
                logger.info(
                    "[Worker] Successfully saved XML for rule '%s': %s",
                    rule_ref.name,
                    file_path,
                )
            except (IOError, OSError) as write_err:
                logger.error(
                    "[Worker] Filesystem write error for rule '%s': %s",
                    rule_ref.name,
                    write_err,
                )
                storage.record_result(
                    LogEntry(
                        rule_name=rule_ref.name,
                        stage_name=rule_ref.stage_name,
                        output_filename=filename,
                        status="failure",
                        timestamp=datetime.now().isoformat(),
                        failure_reason=f"Filesystem write error: {write_err}",
                    )
                )
        else:
            capture_screenshot(
                driver, config.output_dir, f"{rule_ref.stage_name}_{rule_ref.name}"
            )
            storage.record_result(
                LogEntry(
                    rule_name=rule_ref.name,
                    stage_name=rule_ref.stage_name,
                    output_filename=filename,
                    status="failure",
                    timestamp=datetime.now().isoformat(),
                    failure_reason=result.error_message,
                )
            )
            logger.error(
                "[Worker] Failed to extract XML for rule '%s' in stage '%s': %s",
                rule_ref.name,
                rule_ref.stage_name,
                result.error_message,
            )
    except Exception as exc:
        logger.error(
            "[Worker] Unhandled error processing rule '%s': %s",
            rule_ref.name,
            exc,
        )
        filename = storage.build_filename(rule_ref.stage_name, rule_ref.name)
        storage.record_result(
            LogEntry(
                rule_name=rule_ref.name,
                stage_name=rule_ref.stage_name,
                output_filename=filename,
                status="failure",
                timestamp=datetime.now().isoformat(),
                failure_reason=f"Worker error: {exc}",
            )
        )
    finally:
        if driver is not None:
            quit_driver(driver)


def main() -> int:
    """Main entry point. Orchestrates the full pipeline.

    Steps:
    1. Load config (CLI + env + .env)
    2. Setup logging
    3. Create output directory
    4. Launch browser
    5. Authenticate
    6. Navigate to Case Type
    7. For each stage: discover rules, extract XML for each
    8. Write execution log
    9. Cleanup and exit

    Returns:
        0 on success (all rules downloaded), 1 if any failures occurred.
        Catches all unhandled exceptions at this level.
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

        # --- Task 11.3: Stage and rule processing loop ---
        stages = discover_stages(driver, config.stage_list)
        total_stages = len(stages)

        if config.parallel_workers > 1:
            # --- Parallel mode: discover all rules first, then process in parallel ---
            logger.info(
                "Parallel mode enabled with %d workers — discovering all rules first",
                config.parallel_workers,
            )

            # Discover all rules across all stages using the main browser session
            all_rules: List[RuleRef] = []
            for stage_name in stages:
                rules = discover_rules(driver, stage_name)
                all_rules.extend(rules)
                logger.info(
                    "Discovered %d rules in stage '%s' for parallel processing",
                    len(rules),
                    stage_name,
                )

            # Close the discovery browser session — workers will create their own
            quit_driver(driver)
            driver = None

            # Filter out duplicates before submitting to workers
            rules_to_process: List[RuleRef] = []
            for rule_ref in all_rules:
                filename = storage.build_filename(rule_ref.stage_name, rule_ref.name)
                if storage.is_duplicate(filename):
                    logger.info(
                        "Skipping duplicate rule '%s' (file '%s' already exists)",
                        rule_ref.name,
                        filename,
                    )
                else:
                    rules_to_process.append(rule_ref)

            logger.info(
                "Submitting %d rules to thread pool (%d workers)",
                len(rules_to_process),
                config.parallel_workers,
            )

            # Process rules in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=config.parallel_workers) as executor:
                futures = {
                    executor.submit(
                        _process_rule_worker, rule_ref, config, storage
                    ): rule_ref
                    for rule_ref in rules_to_process
                }
                for future in as_completed(futures):
                    rule_ref = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        logger.error(
                            "Worker raised unhandled exception for rule '%s': %s",
                            rule_ref.name,
                            exc,
                        )

            # Log per-stage completion summaries
            for stage_name in stages:
                stage_rule_count = sum(
                    1 for r in all_rules if r.stage_name == stage_name
                )
                logger.info(
                    "Completed stage '%s' — %d rules processed",
                    stage_name,
                    stage_rule_count,
                )
        else:
            # --- Sequential mode: extract XML for each stage directly ---
            for idx, stage_name in enumerate(stages):
                filename = storage.build_filename("stages", stage_name)

                # Check for duplicates
                if storage.is_duplicate(filename):
                    logger.info(
                        "Skipping duplicate stage '%s' (file '%s' already exists)",
                        stage_name,
                        filename,
                    )
                    continue

                try:
                    xml_content = extract_stage_xml(
                        driver, stage_name, idx, config.case_type_name
                    )

                    if xml_content:
                        # Save XML file
                        try:
                            file_path = storage.save_xml(filename, xml_content)
                            storage.record_result(
                                LogEntry(
                                    rule_name=stage_name,
                                    stage_name="stages",
                                    output_filename=filename,
                                    status="success",
                                    timestamp=datetime.now().isoformat(),
                                    failure_reason=None,
                                )
                            )
                            logger.info(
                                "Saved XML for stage '%s': %s",
                                stage_name,
                                file_path,
                            )
                        except (IOError, OSError) as write_err:
                            logger.error(
                                "Filesystem write error for stage '%s': %s",
                                stage_name,
                                write_err,
                            )
                            storage.record_result(
                                LogEntry(
                                    rule_name=stage_name,
                                    stage_name="stages",
                                    output_filename=filename,
                                    status="failure",
                                    timestamp=datetime.now().isoformat(),
                                    failure_reason=f"Filesystem write error: {write_err}",
                                )
                            )
                    else:
                        # Extraction returned None
                        capture_screenshot(
                            driver, config.output_dir, f"stage_{stage_name}"
                        )
                        storage.record_result(
                            LogEntry(
                                rule_name=stage_name,
                                stage_name="stages",
                                output_filename=filename,
                                status="failure",
                                timestamp=datetime.now().isoformat(),
                                failure_reason="extract_stage_xml returned None",
                            )
                        )
                        logger.error(
                            "Failed to extract XML for stage '%s'", stage_name
                        )

                except Exception as exc:
                    capture_screenshot(
                        driver, config.output_dir, f"stage_{stage_name}"
                    )
                    storage.record_result(
                        LogEntry(
                            rule_name=stage_name,
                            stage_name="stages",
                            output_filename=filename,
                            status="failure",
                            timestamp=datetime.now().isoformat(),
                            failure_reason=f"Unhandled error: {exc}",
                        )
                    )
                    logger.error(
                        "Unhandled error processing stage '%s': %s",
                        stage_name,
                        exc,
                    )

                logger.info("Completed stage '%s'", stage_name)

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
