"""Browser module for WebDriver lifecycle, screenshot capture, and window management.

Manages Chrome WebDriver creation, screenshot capture on failure,
popup/main window switching, and safe driver cleanup.
"""

import logging
import sys
from datetime import datetime
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from pega_xml_downloader.config import AppConfig

logger = logging.getLogger(__name__)


def create_driver(config: AppConfig) -> webdriver.Chrome:
    """Create and configure a Chrome WebDriver instance.

    Configures Chrome with:
    - Headless mode based on config.headless
    - Page load timeout: 60 seconds
    - Implicit wait: 0 seconds (explicit waits only)

    Args:
        config: Application configuration containing headless setting.

    Returns:
        A configured Chrome WebDriver instance.

    Raises:
        SystemExit: If WebDriver initialization fails.
    """
    try:
        chrome_options = Options()
        if config.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        # Performance: disable unnecessary Chrome features
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")  # skip image loading
        chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])

        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(60)
        driver.implicitly_wait(0)

        logger.info(
            "Chrome WebDriver initialized successfully (headless=%s)",
            config.headless,
        )
        return driver
    except Exception as exc:
        logger.error("Failed to initialize Chrome WebDriver: %s", exc)
        sys.exit(1)


def capture_screenshot(
    driver: webdriver.Chrome, output_dir: str, label: str
) -> Optional[str]:
    """Save a screenshot of the current browser state.

    Saves the screenshot to {output_dir}/FAILED_{label}_{timestamp}.png.

    Args:
        driver: The active Chrome WebDriver instance.
        output_dir: Directory where the screenshot will be saved.
        label: Descriptive label for the screenshot filename.

    Returns:
        The file path of the saved screenshot on success, None on failure.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        filename = f"FAILED_{label}_{timestamp}.png"
        filepath = f"{output_dir}/{filename}"
        driver.save_screenshot(filepath)
        logger.info("Screenshot saved: %s", filepath)
        return filepath
    except Exception as exc:
        logger.warning("Failed to capture screenshot: %s", exc)
        return None


def switch_to_popup(driver: webdriver.Chrome, timeout: int = 15) -> str:
    """Wait for a new window handle and switch to it.

    Uses WebDriverWait with an explicit condition to wait for a new window
    handle to appear, then switches the driver context to the popup window.

    Args:
        driver: The active Chrome WebDriver instance.
        timeout: Maximum seconds to wait for the popup window. Default: 15.

    Returns:
        The popup window handle string.

    Raises:
        TimeoutError: If no new window appears within the timeout period.
    """
    main_handle = driver.current_window_handle
    existing_handles = set(driver.window_handles)

    try:
        WebDriverWait(driver, timeout).until(
            EC.new_window_is_opened(list(existing_handles))
        )
    except Exception as exc:
        raise TimeoutError(
            f"No new popup window appeared within {timeout} seconds"
        ) from exc

    # Identify the new handle
    new_handles = set(driver.window_handles) - existing_handles
    popup_handle = new_handles.pop()

    driver.switch_to.window(popup_handle)
    logger.info(
        "Switched to popup window (handle=%s, title='%s')",
        popup_handle,
        driver.title,
    )
    return popup_handle


def switch_to_main(driver: webdriver.Chrome, main_handle: str) -> None:
    """Close the current window and switch back to the main window.

    Args:
        driver: The active Chrome WebDriver instance.
        main_handle: The window handle of the main browser window to return to.
    """
    current_handle = driver.current_window_handle
    logger.info("Closing popup window (handle=%s)", current_handle)
    driver.close()
    driver.switch_to.window(main_handle)
    logger.info(
        "Switched back to main window (handle=%s, title='%s')",
        main_handle,
        driver.title,
    )


def quit_driver(driver: webdriver.Chrome) -> None:
    """Safely quit the WebDriver, logging any errors.

    Args:
        driver: The Chrome WebDriver instance to quit.
    """
    try:
        driver.quit()
        logger.info("WebDriver quit successfully")
    except Exception as exc:
        logger.error("Error during WebDriver quit: %s", exc)
