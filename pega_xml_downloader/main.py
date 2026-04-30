"""Main orchestrator module for the Pega XML Downloader.

Wires all modules together and drives the full pipeline:
config → logger → browser → auth → navigator → extractor → storage.

Supports downloading XML for multiple Case Types in a single browser session.
"""

import logging
import os
import traceback
from datetime import datetime
from typing import Optional

from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

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
    extract_stage_flows_xml,
    navigate_to_case_type,
)
from pega_xml_downloader.storage import LogEntry, StorageManager

logger = logging.getLogger(__name__)


def _navigate_back_to_case_types(driver: Chrome) -> None:
    """Navigate back to the Case Types list in Dev Studio.

    Called between Case Type iterations. Fully resets iframe context to
    default_content first, then re-enters the Developer iframe and clicks
    the Case Types tab. This ensures stale PegaGadget iframes from the
    previous case type don't interfere with the next navigation.

    Args:
        driver: The active Chrome WebDriver instance.
    """
    try:
        logger.info("Navigating back to Case Types list for next Case Type")

        # Always start from default content to clear any stale iframe context
        driver.switch_to.default_content()

        # Switch into the Developer iframe
        dev_iframe = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "iframe#Developer, iframe[name='Developer']")
            )
        )
        driver.switch_to.frame(dev_iframe)

        # Click the Case Types tab to return to the list
        case_types_tab = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//div[@role='tab' and @title='Case Types'] | "
                    "//div[@data-role='tab' and @title='Case Types'] | "
                    "//*[@title='Case Types' and contains(@class,'header')]",
                )
            )
        )
        driver.execute_script("arguments[0].click();", case_types_tab)
        logger.info("Clicked Case Types tab — back at Case Types list")

        # Wait for the Case Types list to reload
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH, "//a[contains(@class,'explorer_primary')]")
            )
        )
        logger.info("Case Types list loaded — ready for next Case Type")

        # Return to default content so navigate_to_case_type starts clean
        driver.switch_to.default_content()

    except Exception as exc:
        logger.warning(
            "Could not navigate back to Case Types list cleanly: %s — "
            "will attempt full navigation for next Case Type",
            exc,
        )
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


def _process_case_type(
    driver: Chrome,
    case_type_name: str,
    config: AppConfig,
    storage: StorageManager,
) -> bool:
    """Navigate to a Case Type, extract its XML, and save it.

    Args:
        driver: The active Chrome WebDriver instance.
        case_type_name: Name of the Case Type to process.
        config: Application configuration.
        storage: StorageManager instance for file I/O and logging.

    Returns:
        True if extraction succeeded, False if it failed.
    """
    logger.info("=" * 60)
    logger.info("Processing Case Type: '%s'", case_type_name)
    logger.info("=" * 60)

    try:
        navigate_to_case_type(driver, case_type_name, config.output_dir)
    except NavigationError as exc:
        logger.error("Navigation failed for Case Type '%s': %s", case_type_name, exc)
        extraction_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{sanitize_filename(case_type_name)}_{extraction_ts}.xml"
        storage.record_result(
            LogEntry(
                rule_name=case_type_name,
                stage_name="CaseType",
                output_filename=filename,
                status="failure",
                timestamp=datetime.now().isoformat(),
                failure_reason=f"Navigation error: {exc}",
            )
        )
        return False

    logger.info(
        "Opened Case Type '%s' — proceeding to Actions → View XML",
        case_type_name,
    )

    extraction_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    case_type_safe = sanitize_filename(case_type_name)

    # Create a subfolder for this Case Type
    case_type_dir = os.path.join(config.output_dir, case_type_safe)
    os.makedirs(case_type_dir, exist_ok=True)
    logger.info("Output folder: %s", case_type_dir)

    filename = f"{case_type_safe}_{extraction_ts}.xml"
    logger.info("Output filename: %s", filename)

    xml_content = extract_case_type_xml(driver, case_type_name, config.output_dir)

    if xml_content:
        try:
            file_path = os.path.join(case_type_dir, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(xml_content)
            logger.info("Saved XML file: %s", file_path)
            storage.record_result(
                LogEntry(
                    rule_name=case_type_name,
                    stage_name="CaseType",
                    output_filename=filename,
                    status="success",
                    timestamp=datetime.now().isoformat(),
                    failure_reason=None,
                )
            )
            logger.info(
                "Successfully saved XML for Case Type '%s': %s",
                case_type_name,
                file_path,
            )

            # Now extract XML for each flow in the Stages tab
            logger.info("--- Extracting stage flow XMLs for '%s' ---", case_type_name)
            flow_results = extract_stage_flows_xml(driver, case_type_name, config.output_dir)

            for flow_name, flow_xml in flow_results:
                flow_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                flow_filename = f"{case_type_safe}_{sanitize_filename(flow_name)}_{flow_ts}.xml"

                if flow_xml:
                    try:
                        flow_path = os.path.join(case_type_dir, flow_filename)
                        with open(flow_path, "w", encoding="utf-8") as f:
                            f.write(flow_xml)
                        logger.info("Saved flow XML file: %s", flow_path)
                        storage.record_result(
                            LogEntry(
                                rule_name=f"{case_type_name} > {flow_name}",
                                stage_name="StageFlow",
                                output_filename=flow_filename,
                                status="success",
                                timestamp=datetime.now().isoformat(),
                                failure_reason=None,
                            )
                        )
                        logger.info("Saved flow XML '%s': %s", flow_name, flow_path)
                    except (IOError, OSError) as write_err:
                        logger.error("Write error for flow '%s': %s", flow_name, write_err)
                        storage.record_result(
                            LogEntry(
                                rule_name=f"{case_type_name} > {flow_name}",
                                stage_name="StageFlow",
                                output_filename=flow_filename,
                                status="failure",
                                timestamp=datetime.now().isoformat(),
                                failure_reason=f"Write error: {write_err}",
                            )
                        )
                else:
                    storage.record_result(
                        LogEntry(
                            rule_name=f"{case_type_name} > {flow_name}",
                            stage_name="StageFlow",
                            output_filename=flow_filename,
                            status="failure",
                            timestamp=datetime.now().isoformat(),
                            failure_reason="Flow XML extraction returned None",
                        )
                    )

            return True
        except (IOError, OSError) as write_err:
            logger.error(
                "Filesystem write error for Case Type '%s': %s",
                case_type_name,
                write_err,
            )
            storage.record_result(
                LogEntry(
                    rule_name=case_type_name,
                    stage_name="CaseType",
                    output_filename=filename,
                    status="failure",
                    timestamp=datetime.now().isoformat(),
                    failure_reason=f"Filesystem write error: {write_err}",
                )
            )
            return False
    else:
        capture_screenshot(driver, config.output_dir, f"view_xml_{case_type_name}")
        storage.record_result(
            LogEntry(
                rule_name=case_type_name,
                stage_name="CaseType",
                output_filename=filename,
                status="failure",
                timestamp=datetime.now().isoformat(),
                failure_reason="extract_case_type_xml returned None",
            )
        )
        logger.error("Failed to extract XML for Case Type '%s'", case_type_name)
        return False


def main() -> int:
    """Main entry point. Orchestrates the full pipeline.

    Steps:
    1. Load config (CLI + env + .env)
    2. Setup logging
    3. Create output directory
    4. Launch browser
    5. Authenticate once
    6. For each Case Type in case_type_names:
       a. Navigate to Dev Studio → Case Types → target → Actions → Open
       b. Click Actions → View XML
       c. Save XML as {CaseTypeName}_{YYYYMMDD_HHMMSS}.xml
       d. Navigate back to Case Types list (if more remain)
    7. Write execution log
    8. Cleanup and exit

    Returns:
        0 on success (all case types downloaded), 1 if any failures occurred.
    """
    driver: Optional[Chrome] = None
    storage: Optional[StorageManager] = None
    config: Optional[AppConfig] = None

    try:
        cli_args = parse_cli_args()
        config = load_config(cli_args)

        setup_logging(config.log_level, config.output_dir)

        # Use a generic storage manager (not tied to a single case type name)
        storage = StorageManager(config.output_dir, "PegaXML")
        storage.ensure_output_dir()

        total = len(config.case_type_names)
        logger.info(
            "Pega XML Downloader starting — %d Case Type(s) to process: %s",
            total,
            config.case_type_names,
        )

        driver = create_driver(config)
        login(driver, config)

        successes = 0
        failures = 0

        for idx, case_type_name in enumerate(config.case_type_names):
            success = _process_case_type(driver, case_type_name, config, storage)
            if success:
                successes += 1
            else:
                failures += 1

            # Navigate back to Case Types list before processing the next one
            if idx < total - 1:
                _navigate_back_to_case_types(driver)

        # Write execution log and print summary
        storage.write_execution_log()

        logger.info(
            "Run complete — %d Case Type(s) processed: %d successful, %d failed",
            total,
            successes,
            failures,
        )

        quit_driver(driver)
        driver = None

        return 1 if failures > 0 else 0

    except Exception:
        logger.error(
            "Unhandled exception in main:\n%s", traceback.format_exc()
        )
        if driver is not None and config is not None:
            capture_screenshot(driver, config.output_dir, "unhandled_exception")
        return 1

    finally:
        if storage is not None:
            try:
                storage.write_execution_log()
            except Exception:
                pass
        if driver is not None:
            quit_driver(driver)
