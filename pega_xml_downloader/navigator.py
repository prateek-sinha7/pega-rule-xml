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
    logger.info("Locating Case Type '%s'", case_type_name)
    try:
        _wait_for_mask_to_clear(driver)

        # Record existing PegaGadget iframes BEFORE clicking the case type link
        # so we can detect the NEW summary gadget that appears after clicking
        gadgets_before_case_type_click = {
            el.get_attribute("id")
            for el in driver.find_elements(
                By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']"
            )
        }
        logger.info(
            "PegaGadget iframes before clicking case type: %s",
            gadgets_before_case_type_click,
        )

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
        # Collect all available case type names to help the user correct the spelling
        try:
            available = driver.execute_script(
                """
                return Array.from(
                    document.querySelectorAll('a.explorer_primary, a[class*="explorer_primary"]')
                ).map(el => el.textContent.trim() || el.getAttribute('title') || '').filter(t => t);
                """
            )
        except Exception:
            available = []

        if available:
            logger.error(
                "Case Type '%s' not found. Available case types are: %s",
                case_type_name,
                available,
            )
        else:
            logger.error(
                "Case Type '%s' not found in the Case Types tree. "
                "Check the spelling — it must match exactly as shown in Pega Dev Studio.",
                case_type_name,
            )
        capture_screenshot(driver, output_dir, "case_type_not_found")
        raise NavigationError(
            f"Case Type '{case_type_name}' not found. "
            f"Available: {available}" if available else
            f"Case Type '{case_type_name}' not found in the Case Types tree"
        ) from exc

    # Step 4: Find the NEW PegaGadget that loaded the case type summary,
    # then click Actions → Open in it.
    logger.info("Looking for toolbar Actions → Open")
    try:
        # Find the new PegaGadget that appeared after clicking the case type link
        # It contains the case type summary with the Actions → Open button
        def _summary_gadget_appeared(d):
            current = {
                el.get_attribute("id")
                for el in d.find_elements(
                    By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']"
                )
            }
            new_ones = current - gadgets_before_case_type_click
            return list(new_ones) if new_ones else False

        logger.info("Waiting for case type summary PegaGadget to appear...")
        summary_gadget_ids = WebDriverWait(driver, 60).until(_summary_gadget_appeared)
        summary_gadget_id = summary_gadget_ids[0]
        logger.info("Case type summary loaded in: id='%s'", summary_gadget_id)

        summary_gadget_el = driver.find_element(
            By.CSS_SELECTOR, f"iframe#{summary_gadget_id}"
        )
        driver.switch_to.frame(summary_gadget_el)
        logger.info("Switched to case type summary PegaGadget: id='%s'", summary_gadget_id)
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

        # Record existing PegaGadget iframe IDs BEFORE clicking Open
        # so we can detect the NEW rule editor gadget that appears after Open
        driver.switch_to.default_content()
        dev_iframe_ref = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "iframe#Developer, iframe[name='Developer']")
            )
        )
        driver.switch_to.frame(dev_iframe_ref)
        gadgets_before_open = {
            el.get_attribute("id")
            for el in driver.find_elements(
                By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']"
            )
        }
        logger.info("PegaGadget iframes BEFORE clicking Open: %s", gadgets_before_open)

        # Switch back into the summary gadget to click Open
        summary_el_again = driver.find_element(
            By.CSS_SELECTOR, f"iframe#{summary_gadget_id}"
        )
        driver.switch_to.frame(summary_el_again)
        logger.info("Re-entered summary gadget '%s' to click Open", summary_gadget_id)

        # Click "Open" in the Actions dropdown        driver.switch_to.frame(gadget_els_now_sorted[0])
        logger.info("Re-entered PegaGadget0Ifr to click Open")

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

        # After Actions → Open, wait for a NEW PegaGadget iframe to appear
        # (one that wasn't in gadgets_before_open).
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

            # Wait for a NEW PegaGadget iframe to appear (not in gadgets_before_open)
            def _new_gadget_appeared(d):
                current_ids = {
                    el.get_attribute("id")
                    for el in d.find_elements(
                        By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']"
                    )
                }
                new_ones = current_ids - gadgets_before_open
                return list(new_ones) if new_ones else False

            logger.info("Waiting for new PegaGadget iframe to appear after Open...")
            new_ids = WebDriverWait(driver, 60).until(_new_gadget_appeared)
            new_id = new_ids[0]
            logger.info("New PegaGadget iframe appeared: id='%s'", new_id)

            # Switch into the new iframe
            new_el = driver.find_element(By.CSS_SELECTOR, f"iframe#{new_id}")
            driver.switch_to.frame(new_el)
            logger.info("Switched to new PegaGadget iframe: id='%s'", new_id)
            _wait_for_page_ready(driver, timeout=60)

        except Exception as exc:
            logger.warning("Could not enter new PegaGadget iframe after Actions → Open: %s", exc)

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
    """Extract XML by navigating into the correct PegaGadget iframe and
    clicking Actions → View XML.

    This function assumes navigate_to_case_type() has already been called
    and Actions → Open has been clicked. It re-enters the iframe chain from
    default_content to ensure it is always in the correct context, then
    clicks Actions → View XML, handles the popup, and returns the XML.

    Args:
        driver: The active Chrome WebDriver instance.
        case_type_name: Name of the Case Type (used for logging only).
        output_dir: Directory for screenshots on failure.

    Returns:
        The XML content string, or None if extraction fails.
    """
    main_handle = driver.window_handles[0]

    logger.info(
        "Starting Actions → View XML extraction for Case Type '%s'",
        case_type_name,
    )

    try:
        # Always re-enter the iframe chain from scratch to ensure correct context.
        # Go: default_content → Developer iframe → the new PegaGadget iframe
        # that was opened by Actions → Open (tracked via gadgets_before_open).
        logger.info("Re-entering iframe chain from default_content for View XML")
        driver.switch_to.default_content()

        dev_iframe = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "iframe#Developer, iframe[name='Developer']")
            )
        )
        driver.switch_to.frame(dev_iframe)
        logger.info("Switched to Developer iframe")

        # Find all PegaGadget iframes and pick the highest-numbered one
        # (the one opened by Actions → Open is always the highest)
        gadget_els = driver.find_elements(
            By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']"
        )

        def _gadget_num(el):
            gid = el.get_attribute("id") or ""
            try:
                return int(gid.replace("PegaGadget", "").replace("Ifr", ""))
            except ValueError:
                return -1

        gadget_els_sorted = sorted(gadget_els, key=_gadget_num)
        all_ids = [el.get_attribute("id") for el in gadget_els_sorted]
        logger.info("PegaGadget iframes available: %s", all_ids)

        target_el = gadget_els_sorted[-1]
        target_id = target_el.get_attribute("id")
        logger.info("Switching into PegaGadget iframe: id='%s'", target_id)
        driver.switch_to.frame(target_el)
        logger.info("Inside PegaGadget iframe: id='%s'", target_id)

        _wait_for_page_ready(driver, timeout=30)

        # Click Actions → View XML
        logger.info("Looking for 'Actions' toolbar button for View XML")
        actions_button = WebDriverWait(driver, 30).until(
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
        logger.info("Found 'Actions' button, clicking")
        driver.execute_script("arguments[0].click();", actions_button)
        logger.info("Clicked 'Actions' button")

        _wait_for_mask_to_clear(driver)
        time.sleep(1)

        # Dump dropdown items for debugging
        try:
            menu_items = driver.execute_script(
                "return Array.from(document.querySelectorAll("
                "'[class*=menu] a, [role=menuitem], li a'"
                ")).map(e => e.textContent.trim()).filter(t => t);"
            )
            logger.info("Actions dropdown items: %s", menu_items)
        except Exception:
            pass

        # Find and click View XML — retry up to 3 times if dropdown closes
        view_xml_item = None
        for attempt in range(3):
            try:
                view_xml_item = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            "//a[contains(text(),'View XML')] | "
                            "//span[contains(text(),'View XML')]/ancestor::a | "
                            "//*[@role='menuitem'][contains(text(),'View XML')] | "
                            "//li//a[contains(text(),'View XML')]",
                        )
                    )
                )
                logger.info("Found 'View XML' on attempt %d", attempt + 1)
                break
            except TimeoutException:
                if attempt < 2:
                    logger.info("'View XML' not found (attempt %d) — reopening Actions", attempt + 1)
                    try:
                        btn = driver.find_element(
                            By.XPATH,
                            "//button[normalize-space(text())='Actions'] | "
                            "//a[normalize-space(text())='Actions']"
                        )
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1)
                    except Exception:
                        pass
                else:
                    raise TimeoutException(
                        f"'View XML' not found in Actions dropdown for '{case_type_name}'"
                    )

        logger.info("Clicking 'View XML'")
        driver.execute_script("arguments[0].click();", view_xml_item)
        logger.info("Clicked 'View XML' — waiting for popup")

        # Wait for popup window
        time.sleep(3)
        current_handles = set(driver.window_handles)
        logger.info("Window handles after View XML: %d — %s", len(current_handles), current_handles)

        if len(current_handles) > 1:
            new_handles = current_handles - {main_handle}
            popup_handle = new_handles.pop()
            logger.info("Switching to popup window: %s", popup_handle)
            driver.switch_to.window(popup_handle)
            logger.info("Switched to popup (title='%s')", driver.title)
        else:
            logger.info("No new window — checking for inline XML or iframe")
            try:
                new_iframe = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//iframe[contains(@src,'xml') or contains(@name,'xml')]")
                    )
                )
                driver.switch_to.frame(new_iframe)
                logger.info("Switched into XML iframe")
            except TimeoutException:
                logger.info("No XML iframe — XML should be inline")

        # Wait for popup to load
        _wait_for_page_ready(driver, timeout=30)
        logger.info("Popup loaded (title='%s', URL: %s)", driver.title, driver.current_url)

        # Switch into nested iframes if present
        xml_content = None
        try:
            popup_iframes = driver.find_elements(By.TAG_NAME, "iframe")
            if popup_iframes:
                logger.info("Found %d iframe(s) in popup — switching into first", len(popup_iframes))
                driver.switch_to.frame(popup_iframes[0])
                _wait_for_page_ready(driver, timeout=15)
                nested = driver.find_elements(By.TAG_NAME, "iframe")
                if nested:
                    logger.info("Found %d nested iframe(s) — switching into first", len(nested))
                    driver.switch_to.frame(nested[0])
                    _wait_for_page_ready(driver, timeout=15)
        except Exception as iframe_exc:
            logger.warning("Could not switch into popup iframe: %s", iframe_exc)

        # Extract XML — Chrome wraps it in webkit-xml-viewer-source-xml div
        logger.info("Extracting XML content")
        try:
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
                logger.info("Extracted XML (%d characters)", len(xml_content))
            else:
                raise ValueError("webkit-xml-viewer div empty")
        except Exception as js_exc:
            logger.info("JS extraction failed (%s) — using page_source", js_exc)
            try:
                page_src = driver.page_source
                if page_src and page_src.strip():
                    xml_content = page_src
                    logger.info("Extracted XML from page_source (%d characters)", len(xml_content))
                else:
                    body = driver.find_element(By.TAG_NAME, "body")
                    xml_content = body.text
                    logger.info("Extracted XML from body (%d characters)", len(xml_content))
            except Exception as body_exc:
                logger.error("Could not extract XML: %s", body_exc)
                xml_content = None

        if not xml_content or not xml_content.strip():
            logger.warning("XML empty for Case Type '%s'", case_type_name)
            try:
                if len(set(driver.window_handles)) > 1:
                    driver.close()
                    driver.switch_to.window(main_handle)
            except Exception:
                pass
            return None

        logger.info(
            "Successfully extracted XML for Case Type '%s' (%d characters)",
            case_type_name, len(xml_content),
        )

        # Close popup and return to main window
        current_handles_after = set(driver.window_handles)
        if len(current_handles_after) > 1:
            driver.close()
            driver.switch_to.window(main_handle)
            logger.info("Closed popup, returned to main window")
        else:
            try:
                driver.back()
                _wait_for_page_ready(driver, timeout=30)
                logger.info("Navigated back (inline XML)")
            except Exception as back_exc:
                logger.warning("Could not navigate back: %s", back_exc)

        return xml_content

    except TimeoutException as exc:
        logger.error("Timeout during View XML for '%s': %s", case_type_name, exc)
        capture_screenshot(driver, output_dir, f"view_xml_timeout_{case_type_name}")
        try:
            if len(set(driver.window_handles)) > 1:
                driver.close()
                driver.switch_to.window(main_handle)
        except Exception:
            pass
        return None
    except Exception as exc:
        logger.error("Error during View XML for '%s': %s", case_type_name, exc)
        capture_screenshot(driver, output_dir, f"view_xml_error_{case_type_name}")
        try:
            if len(set(driver.window_handles)) > 1:
                driver.close()
                driver.switch_to.window(main_handle)
        except Exception:
            pass
        return None


