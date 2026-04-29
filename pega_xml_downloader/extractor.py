"""Extractor module for rule XML extraction with retry logic.

Handles the XML extraction workflow for a single rule: clicking Actions → View XML,
switching to the popup window, extracting XML content, and returning to the main window.
Includes exponential backoff retry logic for transient failures.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from pega_xml_downloader.auth import AuthenticationError
from pega_xml_downloader.browser import switch_to_main, switch_to_popup
from pega_xml_downloader.navigator import NavigationError, RuleRef

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when XML extraction from a rule fails."""

    pass


@dataclass
class ExtractionResult:
    """Result of an XML extraction attempt.

    Attributes:
        rule_ref: Reference to the rule that was processed.
        success: Whether extraction succeeded.
        xml_content: Extracted XML text (None on failure).
        error_message: Error description (None on success).
        attempts: Number of attempts made.
    """

    rule_ref: RuleRef
    success: bool
    xml_content: Optional[str] = None
    error_message: Optional[str] = None
    attempts: int = 1


def _attempt_extraction(driver: Chrome, rule_ref: RuleRef, main_handle: str) -> str:
    """Perform a single extraction attempt for a rule's XML content.

    Steps:
    1. Find the rule element using rule_ref.locator
    2. Find and click the Actions menu for that rule
    3. Find and click "View XML" in the Actions dropdown
    4. Switch to the XML popup window
    5. Extract the XML text content from the popup
    6. Close popup and return to main window

    Args:
        driver: The active Chrome WebDriver instance.
        rule_ref: Reference to the rule to extract XML from.
        main_handle: The window handle of the main browser window.

    Returns:
        The extracted XML content string.

    Raises:
        ExtractionError: If any step of the extraction fails.
    """
    wait = WebDriverWait(driver, 15)

    try:
        # Step 1: Find the rule element using its locator
        logger.info(
            "Finding rule element '%s' using locator: %s",
            rule_ref.name,
            rule_ref.locator,
        )
        rule_element = wait.until(
            EC.presence_of_element_located((By.XPATH, rule_ref.locator))
        )
        logger.info("Found rule element '%s'", rule_ref.name)

        # Step 2: Find and click the Actions menu for this rule
        logger.info("Finding Actions menu for rule '%s'", rule_ref.name)
        actions_menu = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    f"{rule_ref.locator}/ancestor::tr//button[contains(text(),'Actions') or contains(@title,'Actions')] | "
                    f"{rule_ref.locator}/ancestor::div[contains(@class,'row')]//button[contains(text(),'Actions') or contains(@title,'Actions')] | "
                    f"{rule_ref.locator}/following::*[contains(text(),'Actions')][1]",
                )
            )
        )
        logger.info("Found Actions menu for rule '%s'", rule_ref.name)
        actions_menu.click()
        logger.info("Clicked Actions menu for rule '%s'", rule_ref.name)

        # Step 3: Find and click "View XML" in the Actions dropdown
        logger.info("Finding 'View XML' menu item for rule '%s'", rule_ref.name)
        view_xml_item = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(text(),'View XML')] | "
                    "//span[contains(text(),'View XML')]/ancestor::a | "
                    "//li[contains(text(),'View XML')] | "
                    "//*[@role='menuitem'][contains(text(),'View XML')]",
                )
            )
        )
        logger.info("Found 'View XML' menu item for rule '%s'", rule_ref.name)
        view_xml_item.click()
        logger.info("Clicked 'View XML' for rule '%s'", rule_ref.name)

        # Step 4: Switch to the XML popup window
        logger.info(
            "Switching to XML popup window for rule '%s'", rule_ref.name
        )
        switch_to_popup(driver, timeout=15)
        logger.info(
            "Switched to XML popup window for rule '%s'", rule_ref.name
        )

        # Step 5: Extract the XML text content from the popup
        logger.info("Extracting XML content from popup for rule '%s'", rule_ref.name)
        # The XML is typically displayed in a <pre> element or directly in the <body>
        xml_element = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//pre | //body")
            )
        )
        xml_content = xml_element.text
        logger.info(
            "Extracted XML content for rule '%s' (%d characters)",
            rule_ref.name,
            len(xml_content),
        )

        # Step 6: Close popup and return to main window
        logger.info(
            "Closing popup and switching back to main window for rule '%s'",
            rule_ref.name,
        )
        switch_to_main(driver, main_handle)
        logger.info(
            "Returned to main window after extracting rule '%s'",
            rule_ref.name,
        )

        return xml_content

    except (TimeoutException, NoSuchElementException) as exc:
        # Attempt to recover by switching back to main window if we're in a popup
        _safe_return_to_main(driver, main_handle)
        raise ExtractionError(
            f"Failed to extract XML for rule '{rule_ref.name}': {exc}"
        ) from exc
    except TimeoutError as exc:
        # TimeoutError from switch_to_popup
        _safe_return_to_main(driver, main_handle)
        raise ExtractionError(
            f"XML popup did not open for rule '{rule_ref.name}': {exc}"
        ) from exc
    except Exception as exc:
        # Catch-all for unexpected errors during extraction
        _safe_return_to_main(driver, main_handle)
        raise ExtractionError(
            f"Unexpected error extracting XML for rule '{rule_ref.name}': {exc}"
        ) from exc


def _safe_return_to_main(driver: Chrome, main_handle: str) -> None:
    """Attempt to return to the main window safely, ignoring errors.

    This is a recovery helper used when extraction fails mid-way through
    the popup workflow.

    Args:
        driver: The active Chrome WebDriver instance.
        main_handle: The window handle of the main browser window.
    """
    try:
        current_handle = driver.current_window_handle
        if current_handle != main_handle:
            driver.close()
            driver.switch_to.window(main_handle)
            logger.info("Recovered: returned to main window after extraction failure")
    except Exception:
        # If we can't even determine the current handle, try switching directly
        try:
            driver.switch_to.window(main_handle)
        except Exception:
            pass


def extract_rule_xml(
    driver: Chrome,
    rule_ref: RuleRef,
    max_retries: int,
    main_window_handle: str,
) -> ExtractionResult:
    """Extract XML content for a rule with retry logic and exponential backoff.

    Retries up to max_retries times on failure with exponential backoff
    (2s, 4s, 8s... capped at 30s). Does NOT retry authentication failures
    or missing Case Type errors (AuthenticationError, NavigationError) as
    those are terminal conditions.

    Args:
        driver: The active Chrome WebDriver instance.
        rule_ref: Reference to the rule to extract XML from.
        max_retries: Maximum number of retry attempts.
        main_window_handle: The window handle of the main browser window.

    Returns:
        ExtractionResult with success/failure details and attempt count.
    """
    last_error: Optional[str] = None

    for attempt in range(1, max_retries + 1):
        try:
            xml_content = _attempt_extraction(driver, rule_ref, main_window_handle)
            return ExtractionResult(
                rule_ref=rule_ref,
                success=True,
                xml_content=xml_content,
                attempts=attempt,
            )
        except (AuthenticationError, NavigationError) as exc:
            # Non-retryable errors — fail immediately
            logger.error(
                "Non-retryable error for rule '%s' (attempt %d/%d): %s",
                rule_ref.name,
                attempt,
                max_retries,
                exc,
            )
            return ExtractionResult(
                rule_ref=rule_ref,
                success=False,
                error_message=str(exc),
                attempts=attempt,
            )
        except ExtractionError as exc:
            last_error = str(exc)

            if attempt < max_retries:
                # Calculate exponential backoff: 2s, 4s, 8s... capped at 30s
                delay = min(2 ** attempt, 30)
                logger.info(
                    "Retry %d/%d for rule '%s' in %ds — reason: %s",
                    attempt + 1,
                    max_retries,
                    rule_ref.name,
                    delay,
                    last_error,
                )
                time.sleep(delay)
            else:
                # All retries exhausted
                logger.error(
                    "All %d retry attempts exhausted for rule '%s': %s",
                    max_retries,
                    rule_ref.name,
                    last_error,
                )

    return ExtractionResult(
        rule_ref=rule_ref,
        success=False,
        error_message=last_error,
        attempts=max_retries,
    )
