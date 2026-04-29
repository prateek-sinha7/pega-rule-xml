"""Authentication module for Pega Platform login.

Handles the Pega login flow using stable selectors and explicit waits.
Raises AuthenticationError on failure with screenshot capture.
"""

import logging

from selenium.common.exceptions import TimeoutException
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from pega_xml_downloader.browser import capture_screenshot
from pega_xml_downloader.config import AppConfig

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when Pega login fails."""

    pass


def login(driver: Chrome, config: AppConfig) -> None:
    """Navigate to PEGA_URL, enter credentials, and submit the login form.

    Uses stable selectors (name attributes) rather than dynamic IDs.
    Waits up to 30 seconds for the authenticated state after form submission.

    Args:
        driver: The active Chrome WebDriver instance.
        config: Application configuration with pega_url, pega_username,
            and pega_password.

    Raises:
        AuthenticationError: If login does not reach an authenticated state
            within 30 seconds. A screenshot is captured before raising.
    """
    wait = WebDriverWait(driver, 30)

    try:
        # Navigate to the Pega URL
        logger.info("Navigating to Pega login page: %s", config.pega_url)
        driver.get(config.pega_url)
        logger.info("Pega login page loaded (title='%s')", driver.title)

        # Find and fill the username field using stable name attribute
        logger.info("Finding username field (name='UserIdentifier')")
        username_field = wait.until(
            EC.presence_of_element_located((By.NAME, "UserIdentifier"))
        )
        logger.info("Found username field, entering username")
        username_field.clear()
        username_field.send_keys(config.pega_username)
        logger.info("Username entered successfully")

        # Find and fill the password field using stable name attribute
        logger.info("Finding password field (name='Password')")
        password_field = wait.until(
            EC.presence_of_element_located((By.NAME, "Password"))
        )
        logger.info("Found password field, entering password")
        password_field.clear()
        password_field.send_keys(config.pega_password)
        logger.info("Password entered successfully")

        # Find and click the submit button
        logger.info("Finding login submit button")
        submit_button = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            )
        )
        logger.info("Found submit button, clicking to submit login form")
        submit_button.click()
        logger.info("Login form submitted, waiting for authenticated state")

        # Wait for authenticated state - the login form should disappear
        # and the page should transition away from the login page.
        # We detect this by waiting for the username field to become stale
        # (no longer attached to the DOM), indicating a page transition.
        wait.until(EC.staleness_of(username_field))
        logger.info(
            "Authentication successful - login page transitioned "
            "(current URL: %s, title='%s')",
            driver.current_url,
            driver.title,
        )

    except TimeoutException as exc:
        logger.error(
            "Authentication failed: login did not reach authenticated state "
            "within 30 seconds (current URL: %s)",
            driver.current_url,
        )
        capture_screenshot(driver, config.output_dir, "login_failure")
        raise AuthenticationError(
            "Login did not reach authenticated state within 30 seconds"
        ) from exc
    except Exception as exc:
        logger.error("Authentication failed with unexpected error: %s", exc)
        capture_screenshot(driver, config.output_dir, "login_failure")
        raise AuthenticationError(
            f"Login failed with unexpected error: {exc}"
        ) from exc
