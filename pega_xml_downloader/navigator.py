"""Navigator module for Dev Studio navigation and rule/stage discovery.

Handles navigation from an authenticated Pega session to the Case Type
detail view in Dev Studio, and discovers stages and rules within it.
Uses stable element locators and explicit waits throughout.
"""

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

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
    """Wait for Pega's UI loading mask to disappear before interacting.

    Pega shows a semi-transparent overlay (div#pega_ui_mask) during page
    transitions and AJAX loads. Clicking elements while this mask is active
    causes ElementClickInterceptedException.

    Args:
        driver: The active Chrome WebDriver instance.
        timeout: Maximum seconds to wait for the mask to clear.
    """
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located(
                (By.ID, "pega_ui_mask")
            )
        )
        logger.info("Pega UI mask cleared")
    except TimeoutException:
        logger.warning(
            "Pega UI mask did not clear within %d seconds — proceeding anyway",
            timeout,
        )
    except NoSuchElementException:
        # Mask element doesn't exist at all — nothing to wait for
        pass


def _wait_for_page_ready(driver: Chrome, timeout: int = 30) -> None:
    """Wait for the Pega page to fully load and settle.

    Combines multiple checks:
    1. Wait for document.readyState to be 'complete'
    2. Wait for the Pega UI mask to disappear
    3. Wait for any active AJAX/fetch requests to finish
    4. Brief settle time for Pega's client-side rendering

    Args:
        driver: The active Chrome WebDriver instance.
        timeout: Maximum seconds to wait for the page to be ready.
    """
    # 1. Wait for document.readyState == 'complete'
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        logger.info("Document readyState is 'complete'")
    except TimeoutException:
        logger.warning("Document readyState did not reach 'complete' within %ds", timeout)

    # 2. Wait for the Pega UI mask to disappear
    _wait_for_mask_to_clear(driver, timeout)

    # 3. Wait for jQuery/Pega AJAX to settle (if jQuery is present)
    try:
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script(
                "return (typeof jQuery === 'undefined' || jQuery.active === 0)"
            )
        )
        logger.info("No active AJAX requests")
    except TimeoutException:
        logger.warning("AJAX requests did not settle within 10s")
    except Exception:
        pass  # jQuery not available or script error — skip

    # 4. Brief settle time for Pega's client-side rendering to finish
    time.sleep(2)
    logger.info("Page ready after settle wait")


class NavigationError(Exception):
    """Raised when a required navigation target is not found."""

    pass


@dataclass
class RuleRef:
    """Reference to a discovered rule within a stage.

    Attributes:
        name: Display name of the rule.
        stage_name: Name of the parent stage.
        locator: CSS selector or XPath to re-locate the rule element.
        index: Position index within the stage's rule list.
    """

    name: str
    stage_name: str
    locator: str
    index: int


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

        _wait_for_page_ready(driver)
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


def discover_stages(driver: Chrome, stage_list: List[str]) -> List[str]:
    """Identify which stages from stage_list are present in the Case Type detail view.

    Searches the current page for each stage name in the provided list.
    Logs WARNING for any stage not found, INFO with count of discovered stages.

    Args:
        driver: The active Chrome WebDriver instance positioned on the
            Case Type detail view.
        stage_list: Ordered list of stage names to look for.

    Returns:
        List of stage names that were found in the detail view,
        preserving the order from stage_list.
    """
    logger.info("Navigating to Stages section within Case Type detail view")
    found_processes: List[str] = []

    # Wait for the page to be fully loaded
    _wait_for_page_ready(driver)

    # Click the "Stages" tab to show the stages/processes view
    # The tabs are: Processes | Calculations | Stages | Attachment categories | etc.
    # The tab might be an <a> inside a tab list structure
    try:
        # First dump ALL tab-like elements for debugging
        try:
            tabs_html = driver.execute_script(
                """
                var results = [];
                // Search for any tab-like elements
                var allEls = document.querySelectorAll('a, li[role="tab"], [role="tab"], .tab-title');
                for (var i = 0; i < allEls.length; i++) {
                    var txt = allEls[i].textContent.trim();
                    if (txt.length > 0 && txt.length < 30) {
                        results.push('<' + allEls[i].tagName + ' class="' + (allEls[i].className || '').substring(0, 40) + 
                            '" href="' + (allEls[i].getAttribute('href') || '') + '">' + txt + '</' + allEls[i].tagName + '>');
                    }
                    if (results.length > 30) break;
                }
                // Also check for iframes
                var iframes = document.querySelectorAll('iframe');
                for (var j = 0; j < iframes.length; j++) {
                    results.push('IFRAME: id=' + (iframes[j].id || '') + ' name=' + (iframes[j].name || ''));
                }
                return results.join('\\n');
                """
            )
            logger.info("Elements in current frame:\n%s", tabs_html)
        except Exception:
            pass

        stages_tab = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 "//div[contains(@class,'header') and normalize-space(.)='Stages'] | "
                 "//a[normalize-space(.)='Stages'] | "
                 "//li//a[normalize-space(.)='Stages']")
            )
        )
        logger.info("Found 'Stages' tab, JS-clicking it")
        driver.execute_script("arguments[0].click();", stages_tab)
        logger.info("Clicked 'Stages' tab")
        _wait_for_page_ready(driver)
    except TimeoutException:
        logger.warning("Stages tab not found — may already be active or different tab structure")

    # Dynamically discover ALL process/stage names from the Stages section.
    # Process names are in <input type="text"> elements with:
    #   name="$PRH_1$ppyStages$l{index}$ppyStageName"
    #   data-test-id="20141106145911015114570"
    #   value="Program Design" (the process name)
    # IMPORTANT: Only READ values — never click edit/delete/add buttons.
    try:
        process_names = driver.execute_script(
            """
            var results = [];
            var seen = {};
            // Find all stage name input fields
            var inputs = document.querySelectorAll('input[name*="ppyStageName"]');
            for (var i = 0; i < inputs.length; i++) {
                var val = inputs[i].value.trim();
                if (val && !seen[val]) {
                    seen[val] = true;
                    results.push(val);
                }
            }
            // Fallback: find inputs with data-test-id="20141106145911015114570"
            if (results.length === 0) {
                var inputs2 = document.querySelectorAll('input[data-test-id="20141106145911015114570"]');
                for (var j = 0; j < inputs2.length; j++) {
                    var v = inputs2[j].value.trim();
                    if (v && !seen[v]) {
                        seen[v] = true;
                        results.push(v);
                    }
                }
            }
            return results;
            """
        )
        if process_names:
            found_processes = process_names
            logger.info("Dynamically discovered %d processes: %s", len(found_processes), found_processes)
        else:
            logger.warning("No processes found dynamically, falling back to stage_list config")
            # Fall back to configured stage_list
            for stage_name in stage_list:
                try:
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(
                            (By.XPATH, f"//*[contains(text(),'{stage_name}')]")
                        )
                    )
                    found_processes.append(stage_name)
                    logger.info("Found configured process '%s'", stage_name)
                except (TimeoutException, NoSuchElementException):
                    logger.warning("Process '%s' not found — skipping", stage_name)
    except Exception as e:
        logger.error("Error discovering processes: %s", e)
        # Fall back to configured stage_list
        for stage_name in stage_list:
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, f"//*[contains(text(),'{stage_name}')]")
                    )
                )
                found_processes.append(stage_name)
            except (TimeoutException, NoSuchElementException):
                pass

    logger.info(
        "Discovered %d processes to extract: %s",
        len(found_processes),
        found_processes,
    )
    return found_processes


def discover_rules(driver: Chrome, stage_name: str) -> List[RuleRef]:
    """Open/expand a stage and collect ALL rule references before returning.

    Uses the collect-then-process pattern: discovers every rule in the stage
    and builds the complete list before returning. Supports discovery of
    1000+ rules without memory issues by storing only lightweight RuleRef
    objects.

    Args:
        driver: The active Chrome WebDriver instance positioned on the
            Case Type detail view.
        stage_name: The name of the stage to expand and discover rules in.

    Returns:
        List of RuleRef objects representing all rules found in the stage.
    """
    logger.info("Opening stage '%s' to discover rules", stage_name)
    wait = WebDriverWait(driver, 15)

    # Wait for the page to be ready before interacting
    _wait_for_page_ready(driver)

    # Click/expand the stage to reveal its rules
    try:
        stage_element = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    f"//*[contains(@class,'stage') and contains(text(),'{stage_name}')] | "
                    f"//span[text()='{stage_name}'] | "
                    f"//div[text()='{stage_name}'] | "
                    f"//a[text()='{stage_name}'] | "
                    f"//td[text()='{stage_name}'] | "
                    f"//*[@data-test-id and contains(text(),'{stage_name}')]",
                )
            )
        )
        stage_element.click()
        logger.info("Clicked stage '%s' to expand/open it", stage_name)
    except TimeoutException:
        logger.warning(
            "Could not click stage '%s' — it may already be expanded",
            stage_name,
        )

    # Dump the DOM around the stage area for debugging
    try:
        rules_html = driver.execute_script(
            """
            var stageName = arguments[0];
            var results = [];
            // Find elements containing the stage name
            var xpath = "//*[contains(text(),'" + stageName + "')]";
            var stageEls = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            for (var i = 0; i < Math.min(stageEls.snapshotLength, 3); i++) {
                var el = stageEls.snapshotItem(i);
                var container = el;
                for (var j = 0; j < 3 && container.parentElement; j++) {
                    container = container.parentElement;
                }
                results.push('--- Stage container ' + i + ' ---');
                results.push(container.outerHTML.substring(0, 2000));
            }
            // Look for elements with flow/process/step in class or data-test-id
            var flowEls = document.querySelectorAll(
                '[class*="flow"], [class*="Flow"], [class*="process"], [class*="Process"], ' +
                '[class*="step"], [class*="Step"], [data-test-id*="flow"], [data-test-id*="step"], ' +
                '[data-test-id*="process"], [data-test-id*="assignment"]'
            );
            if (flowEls.length > 0) {
                results.push('--- Flow/Process/Step elements (' + flowEls.length + ' found) ---');
                for (var k = 0; k < Math.min(flowEls.length, 5); k++) {
                    results.push(flowEls[k].outerHTML.substring(0, 500));
                }
            }
            return results.join('\\n');
            """,
            stage_name,
        )
        logger.info("Rules/flow DOM context for stage '%s':\n%s", stage_name, rules_html)
    except Exception as debug_exc:
        logger.warning("Could not extract rules DOM context: %s", debug_exc)

    # Wait for the page to settle
    _wait_for_page_ready(driver)

    # Collect all rule elements - use broad selector strategies
    # including Pega-specific patterns from the grid table structure
    rule_elements = driver.find_elements(
        By.XPATH,
        "//tr[contains(@class,'rule')] | "
        "//div[contains(@class,'rule-item') or contains(@class,'rule-list-item')] | "
        "//li[contains(@class,'rule')] | "
        "//table[contains(@class,'rule')]//tr[td] | "
        "//*[@data-test-id][contains(@class,'list-item')] | "
        "//div[contains(@class,'flow-item')] | "
        "//a[contains(@class,'rule-link')] | "
        "//div[contains(@class,'flow')] | "
        "//tr[@data-test-id and @role='row']//a",
    )

    # Build the list of RuleRef objects
    rules: List[RuleRef] = []
    seen_names: set = set()

    for index, element in enumerate(rule_elements):
        try:
            # Extract the rule name from the element text
            rule_name = element.text.strip()
            if not rule_name:
                # Try to get text from child elements
                name_el = element.find_elements(By.XPATH, ".//a | .//span | .//td[1]")
                if name_el:
                    rule_name = name_el[0].text.strip()

            if not rule_name or rule_name in seen_names:
                continue

            seen_names.add(rule_name)

            # Build a stable locator for re-finding this element later
            # Prefer data-test-id, then text-based XPath
            data_test_id = element.get_attribute("data-test-id")
            if data_test_id:
                locator = f"//*[@data-test-id='{data_test_id}']"
            else:
                # Use text-based XPath as the locator
                locator = f"//*[contains(text(),'{rule_name}')]"

            rule_ref = RuleRef(
                name=rule_name,
                stage_name=stage_name,
                locator=locator,
                index=index,
            )
            rules.append(rule_ref)
        except Exception as exc:
            logger.warning(
                "Failed to extract rule info from element at index %d in stage '%s': %s",
                index,
                stage_name,
                exc,
            )
            continue

    logger.info(
        "Discovered %d rules in stage '%s'",
        len(rules),
        stage_name,
    )
    return rules


def extract_stage_xml(
    driver: Chrome, stage_name: str, stage_index: int, case_type_name: str
) -> Optional[str]:
    """Extract XML for a stage by clicking it, then Actions → View XML.

    The driver must already be inside the PegaGadget iframe with the Stages
    view visible. For stage_index == 0 the first stage is already selected;
    for subsequent stages the stage element is clicked first.

    Steps:
    1. If stage_index > 0: click the stage element to select it.
    2. Click the "Actions" toolbar button.
    3. Click "View XML" in the dropdown menu.
    4. Switch to the popup window that opens.
    5. Extract XML text from the popup (<pre> or <body>).
    6. Close popup and return to main window.

    Args:
        driver: The active Chrome WebDriver instance (inside PegaGadget iframe).
        stage_name: Display name of the stage.
        stage_index: 0-based index of the stage in the stages list.
        case_type_name: Name of the Case Type (for logging).

    Returns:
        The XML content string, or None if extraction fails.
    """
    wait = WebDriverWait(driver, 30)
    main_handle = driver.window_handles[0]

    logger.info(
        "Extracting XML for stage '%s' (index=%d) in Case Type '%s'",
        stage_name,
        stage_index,
        case_type_name,
    )

    try:
        # Step 1: If not the first stage, click the stage element to select it
        if stage_index > 0:
            logger.info("Clicking stage '%s' to select it", stage_name)
            # The stage name is in an <input> with name containing "ppyStageName"
            # and value matching the stage name. Click the input to select the row.
            stage_element = wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        f"//input[contains(@name,'ppyStageName') and @value='{stage_name}'] | "
                        f"//input[@data-test-id='20141106145911015114570' and @value='{stage_name}'] | "
                        f"//a[@title='{stage_name}'] | "
                        f"//a[normalize-space(text())='{stage_name}']",
                    )
                )
            )
            driver.execute_script("arguments[0].click();", stage_element)
            logger.info("Clicked stage '%s'", stage_name)
            # Wait for the page to settle after selecting the stage
            _wait_for_page_ready(driver)

        # Step 2: Click the "Actions" toolbar button
        logger.info("Clicking 'Actions' toolbar button for stage '%s'", stage_name)
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
        driver.execute_script("arguments[0].click();", actions_button)
        logger.info("Clicked 'Actions' button for stage '%s'", stage_name)

        # Wait for the dropdown to appear
        _wait_for_mask_to_clear(driver)
        time.sleep(1)  # Brief pause for dropdown animation

        # Step 3: Click "View XML" in the dropdown
        logger.info("Looking for 'View XML' in Actions dropdown for stage '%s'", stage_name)
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
        logger.info("Clicked 'View XML' for stage '%s'", stage_name)

        # Step 4: Switch to the popup window
        logger.info("Waiting for XML popup window for stage '%s'", stage_name)
        switch_to_popup(driver, timeout=20)
        logger.info("Switched to XML popup window for stage '%s'", stage_name)

        # Step 5: Extract XML text from the popup
        logger.info("Extracting XML content from popup for stage '%s'", stage_name)
        xml_element = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH, "//pre | //body")
            )
        )
        xml_content = xml_element.text
        logger.info(
            "Extracted XML for stage '%s' (%d characters)",
            stage_name,
            len(xml_content),
        )

        # Step 6: Close popup and return to main window
        logger.info("Closing popup and returning to main window for stage '%s'", stage_name)
        switch_to_main(driver, main_handle)
        logger.info("Returned to main window after extracting stage '%s'", stage_name)

        # After returning to main window, we need to switch back into the
        # PegaGadget iframe since switch_to_main puts us at the top level
        # Re-enter the Developer iframe then the PegaGadget iframe
        try:
            dev_iframe = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "iframe#Developer, iframe[name='Developer']")
                )
            )
            driver.switch_to.frame(dev_iframe)
            # Switch to the last PegaGadget iframe (the rule view)
            gadget_iframes = driver.find_elements(
                By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']"
            )
            if gadget_iframes:
                driver.switch_to.frame(gadget_iframes[-1])
            logger.info("Re-entered Developer + PegaGadget iframe after popup close")
        except TimeoutException:
            logger.warning(
                "Could not re-enter iframe chain after popup close for stage '%s'",
                stage_name,
            )

        if not xml_content or len(xml_content.strip()) == 0:
            logger.warning("XML content for stage '%s' is empty", stage_name)
            return None

        return xml_content

    except TimeoutException as exc:
        logger.error(
            "Timeout extracting XML for stage '%s': %s", stage_name, exc
        )
        # Try to recover — close any open popup and return to main
        _safe_recover_from_popup(driver, main_handle)
        return None
    except TimeoutError as exc:
        logger.error(
            "Popup did not open for stage '%s': %s", stage_name, exc
        )
        _safe_recover_from_popup(driver, main_handle)
        return None
    except Exception as exc:
        logger.error(
            "Unexpected error extracting XML for stage '%s': %s", stage_name, exc
        )
        _safe_recover_from_popup(driver, main_handle)
        return None


def _safe_recover_from_popup(driver: Chrome, main_handle: str) -> None:
    """Attempt to close any open popup and return to the PegaGadget iframe.

    Used as a recovery mechanism when extract_stage_xml fails mid-way.

    Args:
        driver: The active Chrome WebDriver instance.
        main_handle: The main window handle to return to.
    """
    try:
        current_handle = driver.current_window_handle
        if current_handle != main_handle:
            driver.close()
            driver.switch_to.window(main_handle)
            logger.info("Recovery: closed popup and returned to main window")
    except Exception:
        try:
            driver.switch_to.window(main_handle)
        except Exception:
            pass

    # Try to re-enter the iframe chain (Developer → last PegaGadget)
    try:
        dev_iframe = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "iframe#Developer, iframe[name='Developer']")
            )
        )
        driver.switch_to.frame(dev_iframe)
        gadget_iframes = driver.find_elements(
            By.CSS_SELECTOR, "iframe[id^='PegaGadget'][id$='Ifr']"
        )
        if gadget_iframes:
            driver.switch_to.frame(gadget_iframes[-1])
        logger.info("Recovery: re-entered Developer + PegaGadget iframe")
    except Exception:
        logger.warning("Recovery: could not re-enter iframe chain")
