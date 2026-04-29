"""Navigator module for Dev Studio navigation and rule/stage discovery.

Handles navigation from an authenticated Pega session to the Case Type
detail view in Dev Studio, and discovers stages and rules within it.
Uses stable element locators and explicit waits throughout.
"""

import logging
import time
from typing import Optional

from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from pega_xml_downloader.browser import (
    capture_screenshot,
    switch_to_main,
    switch_to_popup,
)

logger = logging.getLogger(__name__)


def _wait_for_mask_to_clear(driver: Chrome, timeout: int = 30) -> None:
    """Wait for Pega's UI loading mask to disappear before interacting."""
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.ID, "pega_ui_mask"))
        )
        logger.debug("Pega UI mask cleared")
    except TimeoutException:
        logger.warning(
            "Pega UI mask did not clear within %d seconds — proceeding anyway",
            timeout,
        )
    except NoSuchElementException:
        pass  # Mask doesn't exist — nothing to wait for


def _wait_for_page_ready(driver: Chrome, timeout: int = 30) -> None:
    """Wait for the Pega page to fully load and settle.

    Checks:
    1. document.readyState == 'complete'
    2. Pega UI mask gone
    3. jQuery AJAX idle (if present)
    4. Short settle pause (0.5s) for client-side rendering
    """
    # 1. document.readyState
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        logger.debug("Document readyState is 'complete'")
    except TimeoutException:
        logger.warning("Document readyState did not reach 'complete' within %ds", timeout)

    # 2. Pega UI mask
    _wait_for_mask_to_clear(driver, timeout)

    # 3. jQuery AJAX idle
    try:
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script(
                "return (typeof jQuery === 'undefined' || jQuery.active === 0)"
            )
        )
        logger.debug("No active AJAX requests")
    except TimeoutException:
        logger.warning("AJAX requests did not settle within 10s")
    except Exception:
        pass

    # 4. Minimal settle pause — 0.5s instead of 2s
    time.sleep(0.5)
    logger.debug("Page ready")


class NavigationError(Exception):
    """Raised when a required navigation target is not found."""

    pass



def navigate_to_case_type(
    driver: Chrome, case_type_name: str, output_dir: str = "output"
) -> None:
    """Navigate from authenticated session to the Case Type detail view.

    Steps: Dev Studio → Case Types → locate target → Actions → Open.
    Uses stable element locators (data-test-id, text-based XPath, stable classes).
    Logs INFO at each navigation step and confirms success with URL/title.

    Args:
        driver: The active Chrome WebDriver instance (already authenticated).
        case_type_name: The name of the Case Type to open (e.g. "Tax Compliance Training").
        output_dir: Directory for screenshots on failure.

    Raises:
        NavigationError: If the Case Type is not found or navigation fails.
    """
    wait = WebDriverWait(driver, 30)

    # Step 1: Switch to Dev Studio workspace
    # After login, we land in App Studio. Dev Studio is accessed via the
    # workspace switcher menu in the header. The switcher is a dropdown
    # that contains "Dev Studio" as a menu item which calls
    # pega.desktop.wks.switchWorkspace("Developer").
    logger.info("Switching to Dev Studio workspace")
    try:
        _wait_for_page_ready(driver, timeout=60)

        logger.info(
            "Current page — URL: %s, title='%s'",
            driver.current_url,
            driver.title,
        )

        # Strategy 1: Use JavaScript to directly call the workspace switch
        # This is the most reliable approach since it bypasses UI element issues
        try:
            logger.info("Attempting JS workspace switch to Developer")
            driver.execute_script('pega.desktop.wks.switchWorkspace("Developer")')
            logger.info("Executed pega.desktop.wks.switchWorkspace('Developer')")

            # The workspace switch triggers a full page reload/navigation.
            # We must wait for the page to actually change — not just check
            # readyState (which is 'complete' for the OLD page before reload starts).
            # Wait up to 90s for the title to change or Dev Studio elements to appear.
            logger.info("Waiting for Dev Studio to load after workspace switch...")
            WebDriverWait(driver, 90).until(
                lambda d: "App Studio" not in d.title
                or len(d.find_elements(By.XPATH, "//div[@role='tab' and @title='Case Types']")) > 0
                or len(d.find_elements(By.XPATH, "//a[@class='explorer_primary']")) > 0
            )
            logger.info("Page changed after workspace switch — title='%s'", driver.title)
            _wait_for_page_ready(driver, timeout=60)
        except Exception as js_exc:
            logger.info("JS workspace switch failed: %s, trying UI click", js_exc)

            # Strategy 2: Find and click the workspace switcher menu, then Dev Studio
            # First, find the menu trigger (could be a button/icon in the header)
            # Look for common Pega workspace switcher triggers
            try:
                # Try to find the workspace switcher trigger button
                switcher_trigger = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//*[contains(@data-click,'switchWorkspace') or contains(@data-click,'workspace')] | "
                            "//*[contains(@class,'workspace-switcher')] | "
                            "//*[contains(@data-test-id,'workspace')] | "
                            "//button[contains(@class,'studio-switch')]",
                        )
                    )
                )
                logger.info("Found workspace switcher trigger, clicking")
                switcher_trigger.click()
                _wait_for_mask_to_clear(driver)
            except TimeoutException:
                logger.info("No explicit switcher trigger found, looking for Dev Studio menu item directly")

            # Now find and click the "Dev Studio" menu item
            dev_studio_item = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//span[contains(@class,'menu-item-title') and text()='Dev Studio']/ancestor::a | "
                        "//a[@role='menuitem']//span[text()='Dev Studio']/ancestor::a | "
                        "//*[@data-test-id='201803201403490160636_3']//a | "
                        "//a[contains(@data-click,'switchWorkspace') and contains(@data-click,'Developer')]",
                    )
                )
            )
            logger.info("Found 'Dev Studio' menu item, clicking")
            dev_studio_item.click()
            logger.info("Clicked 'Dev Studio' menu item")
            _wait_for_page_ready(driver, timeout=60)

        logger.info(
            "Dev Studio loaded (URL: %s, title='%s')",
            driver.current_url,
            driver.title,
        )
    except TimeoutException as exc:
        logger.error("Failed to switch to Dev Studio workspace")
        capture_screenshot(driver, output_dir, "dev_studio_navigation")
        raise NavigationError("Failed to switch to Dev Studio workspace") from exc

    # Step 2: Click "Case Types" tab in Dev Studio left panel
    # Dev Studio may render content inside iframes. We need to check for
    # iframes and switch into them if the Case Types tab is inside one.
    logger.info("Navigating to Case Types section in Dev Studio")
    try:
        _wait_for_page_ready(driver)

        # The Dev Studio content is inside an iframe named "Developer".
        # Switch to it first, then find Case Types.
        logger.info("Switching to 'Developer' iframe for Dev Studio content")
        try:
            dev_iframe = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "iframe#Developer, iframe[name='Developer']"))
            )
            driver.switch_to.frame(dev_iframe)
            logger.info("Switched to Developer iframe")
        except TimeoutException:
            logger.info("No Developer iframe found, staying in main frame")

        _wait_for_page_ready(driver)

        # Now find and click the Case Types tab inside the iframe.
        # The tab may have a CSS transform that makes Selenium think it's not
        # clickable, so we find it by presence and use JS click.
        case_types_el = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//div[@role='tab' and @title='Case Types'] | "
                    "//div[@data-role='tab' and @title='Case Types'] | "
                    "//*[@title='Case Types' and contains(@class,'header')]",
                )
            )
        )
        logger.info("Found Case Types tab element, JS-clicking it")
        driver.execute_script("arguments[0].click();", case_types_el)
        logger.info("Clicked Case Types tab")

        _wait_for_page_ready(driver)
        logger.info(
            "Case Types section loaded (URL: %s, title='%s')",
            driver.current_url,
            driver.title,
        )

    except TimeoutException as exc:
        logger.error("Failed to navigate to Case Types section within timeout")
        capture_screenshot(driver, output_dir, "case_types_navigation")
        raise NavigationError("Failed to navigate to Case Types section") from exc

    # Step 3: Locate and CLICK the target Case Type in the tree grid
    # In Dev Studio, case types are listed as <a class="explorer_primary"> links
    # inside a tree grid with data-test-id="201711201100250725554"
    logger.info("Locating Case Type '%s'", case_type_name)
    try:
        _wait_for_mask_to_clear(driver)
        case_type_link = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    f"//a[@class='explorer_primary' and @title='{case_type_name}'] | "
                    f"//a[@class='explorer_primary' and text()='{case_type_name}'] | "
                    f"//a[contains(@class,'explorer_primary') and contains(text(),'{case_type_name}')]",
                )
            )
        )
        logger.info("Found Case Type '%s' link, clicking", case_type_name)
        _wait_for_mask_to_clear(driver)
        driver.execute_script("arguments[0].click();", case_type_link)
        logger.info("Clicked Case Type '%s'", case_type_name)
        _wait_for_page_ready(driver, timeout=60)
    except TimeoutException as exc:
        logger.error(
            "Case Type '%s' not found in the Case Types tree", case_type_name
        )
        capture_screenshot(driver, output_dir, "case_type_not_found")
        raise NavigationError(
            f"Case Type '{case_type_name}' not found in the Case Types tree"
        ) from exc

    # Step 4: The Case Type editor loads inside a nested iframe (PegaGadget0Ifr).
    # Switch into it, then click Actions → Open.
    logger.info("Looking for toolbar Actions → Open")
    try:
        # Switch to the PegaGadget iframe where the Case Type editor loads
        logger.info("Switching to PegaGadget iframe for Case Type editor")
        gadget_iframe = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']")
            )
        )
        driver.switch_to.frame(gadget_iframe)
        logger.info("Switched to PegaGadget iframe")
        _wait_for_page_ready(driver, timeout=60)

        # Now find the "Actions" button in the toolbar
        logger.info("Looking for 'Actions' button in toolbar")
        actions_button = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//button[normalize-space(text())='Actions'] | "
                    "//button[.//span[normalize-space(text())='Actions']] | "
                    "//button[contains(@class,'actions') or contains(@class,'Actions')] | "
                    "//a[normalize-space(text())='Actions'] | "
                    "//*[normalize-space(text())='Actions' and (self::button or self::a)]",
                )
            )
        )
        logger.info("Found 'Actions' toolbar button, clicking")
        driver.execute_script("arguments[0].click();", actions_button)
        logger.info("Clicked 'Actions' toolbar button")

        _wait_for_mask_to_clear(driver)

        # Click "Open" in the Actions dropdown
        logger.info("Looking for 'Open' in Actions dropdown")
        open_item = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//a[text()='Open'] | "
                    "//span[text()='Open'] | "
                    "//*[@role='menuitem'][contains(text(),'Open')] | "
                    "//li//a[contains(text(),'Open')] | "
                    "//*[contains(@class,'menu')]//a[contains(text(),'Open')] | "
                    "//*[contains(@class,'menu')]//*[text()='Open']",
                )
            )
        )
        logger.info("Found 'Open' menu item, clicking")
        driver.execute_script("arguments[0].click();", open_item)
        logger.info("Clicked 'Open' — navigating to rule-level view")

        _wait_for_page_ready(driver, timeout=60)

        # After Actions → Open, the Case Type rule view loads in a NEW PegaGadget
        # iframe (PegaGadget1Ifr). Switch back to Developer iframe, then into the
        # LAST PegaGadget iframe which contains the rule view with Stages tab.
        logger.info("Re-entering iframe chain after Actions → Open")
        try:
            driver.switch_to.default_content()
            dev_iframe = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "iframe#Developer, iframe[name='Developer']")
                )
            )
            driver.switch_to.frame(dev_iframe)
            logger.info("Switched back to Developer iframe")

            # Wait for the new PegaGadget iframe to fully load
            # It may take time for the rule view to render
            _wait_for_page_ready(driver, timeout=60)

            # Find ALL PegaGadget iframes and switch to the LAST one
            gadget_iframes = WebDriverWait(driver, 60).until(
                lambda d: [el for el in d.find_elements(By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']") if len(d.find_elements(By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']")) >= 2]
            )
            logger.info("Found %d PegaGadget iframes", len(gadget_iframes))
            for i, gf in enumerate(gadget_iframes):
                logger.info("  PegaGadget[%d]: id='%s'", i, gf.get_attribute("id") or "")

            target_iframe = gadget_iframes[-1]
            logger.info("Switching to last PegaGadget iframe: id='%s'", target_iframe.get_attribute("id") or "")
            driver.switch_to.frame(target_iframe)
            logger.info("Switched to PegaGadget iframe for rule view")
            _wait_for_page_ready(driver, timeout=60)
        except TimeoutException:
            logger.warning("Could not enter PegaGadget iframe after Actions → Open")

        logger.info(
            "Rule-level view opened (URL: %s, title='%s')",
            driver.current_url,
            driver.title,
        )

    except TimeoutException as exc:
        logger.error("Failed to open Case Type via toolbar Actions → Open")
        capture_screenshot(driver, output_dir, "toolbar_actions_open_failed")
        raise NavigationError(
            f"Failed to open Case Type '{case_type_name}' via toolbar Actions → Open"
        ) from exc


def extract_case_type_xml(
    driver: Chrome,
    case_type_name: str,
    output_dir: str = "output",
) -> Optional[str]:
    """Extract XML for the currently open Case Type rule view.

    Called immediately after navigate_to_case_type() has opened the rule-level
    view via Actions → Open. This function simply clicks Actions → View XML on
    that page, switches to the popup, extracts the XML, closes the popup, and
    returns the content.

    No stage tab navigation or per-stage looping is performed.

    Steps:
    1. Wait for the page to settle inside the PegaGadget iframe.
    2. Click the "Actions" toolbar button.
    3. Click "View XML" in the dropdown.
    4. Switch to the XML popup window.
    5. Extract the full XML text from the popup (<pre> or <body>).
    6. Close the popup and return to the main window.

    Args:
        driver: The active Chrome WebDriver instance, already inside the
            PegaGadget iframe with the Case Type rule view loaded.
        case_type_name: Name of the Case Type (used for logging only).
        output_dir: Directory for screenshots on failure.

    Returns:
        The XML content string, or None if extraction fails.
    """
    wait = WebDriverWait(driver, 30)
    main_handle = driver.window_handles[0]

    logger.info(
        "Starting Actions → View XML extraction for Case Type '%s'",
        case_type_name,
    )
    logger.info(
        "Current page state — URL: %s, title='%s'",
        driver.current_url,
        driver.title,
    )

    try:
        # Step 1: Wait for the page to fully settle
        _wait_for_page_ready(driver, timeout=60)
        logger.info("Page settled — ready to click Actions")

        # Step 2: Find and click the "Actions" toolbar button
        logger.info("Looking for 'Actions' toolbar button")
        actions_button = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//button[normalize-space(text())='Actions'] | "
                    "//button[.//span[normalize-space(text())='Actions']] | "
                    "//a[normalize-space(text())='Actions'] | "
                    "//*[normalize-space(text())='Actions' and (self::button or self::a)]",
                )
            )
        )
        logger.info("Found 'Actions' toolbar button, clicking")
        driver.execute_script("arguments[0].click();", actions_button)
        logger.info("Clicked 'Actions' toolbar button")

        # Wait for the dropdown to render
        _wait_for_mask_to_clear(driver)
        time.sleep(1)  # Brief pause for dropdown animation

        # Step 3: Find and click "View XML" in the dropdown
        logger.info("Looking for 'View XML' in Actions dropdown")
        view_xml_item = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//a[contains(text(),'View XML')] | "
                    "//span[contains(text(),'View XML')]/ancestor::a | "
                    "//*[@role='menuitem'][contains(text(),'View XML')] | "
                    "//li//a[contains(text(),'View XML')] | "
                    "//*[contains(@class,'menu')]//a[contains(text(),'View XML')] | "
                    "//*[contains(@class,'menu')]//*[contains(text(),'View XML')]",
                )
            )
        )
        logger.info("Found 'View XML' menu item, clicking")
        driver.execute_script("arguments[0].click();", view_xml_item)
        logger.info("Clicked 'View XML' — waiting for popup window")

        # Step 4: Wait for XML to appear — check if a new window opened.
        # Give Pega 3 seconds to react to the View XML click.
        logger.info("Waiting briefly for Pega to react to 'View XML' click")
        time.sleep(3)

        current_handles = set(driver.window_handles)
        logger.info(
            "Window handles after 'View XML' click: %d handle(s) — %s",
            len(current_handles),
            current_handles,
        )

        if len(current_handles) > 1:
            # A new window opened — switch directly to it (do NOT call switch_to_popup
            # which would wait for yet another new window)
            new_handles = current_handles - {main_handle}
            popup_handle = new_handles.pop()
            logger.info(
                "New window detected — switching directly to handle: %s",
                popup_handle,
            )
            driver.switch_to.window(popup_handle)
            logger.info(
                "Switched to popup window (title='%s', URL: %s)",
                driver.title,
                driver.current_url,
            )
        else:
            # No new window — XML is inline in the current frame or a new iframe
            logger.info(
                "No new window opened — looking for inline XML or new iframe"
            )
            # Check if a new iframe appeared inside the current frame
            try:
                new_iframe = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//iframe[contains(@src,'xml') or contains(@name,'xml') or contains(@id,'xml')]")
                    )
                )
                logger.info("Found XML iframe, switching into it")
                driver.switch_to.frame(new_iframe)
                logger.info("Switched into XML iframe")
            except TimeoutException:
                logger.info("No XML iframe found — XML should be inline in current frame")

        # Step 5: Extract the full XML text from the popup.
        # The popup is a Pega harness — the actual XML is rendered inside
        # a nested iframe within the popup window. We must:
        #   1. Wait for the popup page to fully load
        #   2. Check for nested iframes and switch into the deepest one
        #   3. Extract text from <pre> or <body>
        logger.info("Waiting for popup window to fully load")
        _wait_for_page_ready(driver, timeout=30)
        logger.info(
            "Popup loaded (title='%s', URL: %s)",
            driver.title,
            driver.current_url,
        )

        # Try to find and switch into any iframe inside the popup
        xml_content = None
        try:
            popup_iframes = driver.find_elements(By.TAG_NAME, "iframe")
            if popup_iframes:
                logger.info(
                    "Found %d iframe(s) in popup — switching into first one",
                    len(popup_iframes),
                )
                driver.switch_to.frame(popup_iframes[0])
                logger.info("Switched into popup iframe")
                _wait_for_page_ready(driver, timeout=15)

                # Check for another nested iframe
                nested_iframes = driver.find_elements(By.TAG_NAME, "iframe")
                if nested_iframes:
                    logger.info(
                        "Found %d nested iframe(s) — switching into first nested one",
                        len(nested_iframes),
                    )
                    driver.switch_to.frame(nested_iframes[0])
                    logger.info("Switched into nested iframe")
                    _wait_for_page_ready(driver, timeout=15)
            else:
                logger.info("No iframes in popup — XML should be directly in popup body")
        except Exception as iframe_exc:
            logger.warning("Could not switch into popup iframe: %s", iframe_exc)

        # Now extract the XML text.
        # Chrome wraps XML responses in its built-in viewer:
        #   <div id="webkit-xml-viewer-source-xml">...actual XML...</div>
        # We must extract the innerHTML of that div to get clean XML.
        # Fall back to <pre> text, then raw page_source if the div isn't present.
        logger.info("Extracting XML content from popup")
        try:
            # Primary: extract raw XML from Chrome's XML viewer div
            raw_xml = driver.execute_script(
                """
                var src = document.getElementById('webkit-xml-viewer-source-xml');
                if (src) { return src.innerHTML; }
                var pre = document.querySelector('pre');
                if (pre) { return pre.textContent; }
                return null;
                """
            )
            if raw_xml and raw_xml.strip():
                xml_content = raw_xml.strip()
                logger.info(
                    "Extracted XML via webkit-xml-viewer-source-xml (%d characters)",
                    len(xml_content),
                )
            else:
                raise ValueError("webkit-xml-viewer div not found or empty")
        except Exception as js_exc:
            logger.info("JS extraction failed (%s) — falling back to page_source", js_exc)
            try:
                page_src = driver.page_source
                if page_src and len(page_src.strip()) > 0:
                    xml_content = page_src
                    logger.info(
                        "Extracted XML from page_source (%d characters)",
                        len(xml_content),
                    )
                else:
                    body = driver.find_element(By.TAG_NAME, "body")
                    xml_content = body.text
                    logger.info(
                        "Extracted XML from <body> text (%d characters)",
                        len(xml_content),
                    )
            except Exception as body_exc:
                logger.error("Could not extract XML content: %s", body_exc)
                xml_content = None

        if not xml_content or len(xml_content.strip()) == 0:
            logger.warning(
                "XML content for Case Type '%s' is empty after all extraction attempts",
                case_type_name,
            )
            # Close popup and return None
            try:
                current_handles_check = set(driver.window_handles)
                if len(current_handles_check) > 1:
                    driver.close()
                    driver.switch_to.window(main_handle)
            except Exception:
                pass
            return None

        logger.info(
            "Successfully extracted XML for Case Type '%s' (%d characters)",
            case_type_name,
            len(xml_content),
        )

        # Step 6: Close popup if one was opened, or navigate back if inline
        current_handles_after = set(driver.window_handles)
        if len(current_handles_after) > 1:
            logger.info(
                "Closing popup window (handle=%s) and returning to main window",
                driver.current_window_handle,
            )
            driver.close()
            driver.switch_to.window(main_handle)
            logger.info(
                "Returned to main window (handle=%s) after XML extraction for Case Type '%s'",
                main_handle,
                case_type_name,
            )
        else:
            # Inline — use browser back to return to the rule view
            logger.info("XML was inline — navigating back to rule view")
            try:
                driver.back()
                _wait_for_page_ready(driver, timeout=30)
                logger.info("Navigated back to rule view")
            except Exception as back_exc:
                logger.warning("Could not navigate back: %s", back_exc)

        return xml_content

    except TimeoutException as exc:
        logger.error(
            "Timeout during Actions → View XML for Case Type '%s': %s",
            case_type_name,
            exc,
        )
        capture_screenshot(driver, output_dir, f"view_xml_timeout_{case_type_name}")
        # Attempt recovery — close any stray popup, return to main window
        try:
            current_handles = set(driver.window_handles)
            if len(current_handles) > 1:
                driver.close()
                driver.switch_to.window(main_handle)
                logger.info("Recovery: closed stray popup window")
        except Exception:
            pass
        return None
    except TimeoutError as exc:
        logger.error(
            "XML popup did not open for Case Type '%s': %s",
            case_type_name,
            exc,
        )
        capture_screenshot(driver, output_dir, f"view_xml_popup_timeout_{case_type_name}")
        try:
            current_handles = set(driver.window_handles)
            if len(current_handles) > 1:
                driver.close()
                driver.switch_to.window(main_handle)
        except Exception:
            pass
        return None
    except Exception as exc:
        logger.error(
            "Unexpected error during Actions → View XML for Case Type '%s': %s",
            case_type_name,
            exc,
        )
        capture_screenshot(driver, output_dir, f"view_xml_error_{case_type_name}")
        try:
            current_handles = set(driver.window_handles)
            if len(current_handles) > 1:
                driver.close()
                driver.switch_to.window(main_handle)
        except Exception:
            pass
        return None


