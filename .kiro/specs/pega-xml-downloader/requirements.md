# Requirements Document

## Introduction

This feature is a production-ready Python automation script that uses Selenium to log into the Pega Platform UI, navigate to a specified Case Type ("Tax Compliance Training") in Dev Studio, iterate through all configured stages (Initialization, Primary, Alternatives), open each rule/flow within those stages, extract the XML content via the "View XML" popup, and save each XML file locally with a structured filename. The script must be stable for long runs (1000+ rules), support headless Chrome, avoid duplicate downloads, capture screenshots on failure, and expose a CLI interface with `.env` file support.

## Glossary

- **Downloader**: The Python automation script being specified.
- **Pega_UI**: The Pega Platform web application accessed via browser.
- **Dev_Studio**: The Pega developer interface used to browse and manage rules.
- **Case_Type**: A Pega artifact representing a business process (e.g., "Tax Compliance Training").
- **Stage**: A named phase within a Case Type (e.g., Initialization, Primary, Alternatives).
- **Rule**: A Pega flow or process artifact listed within a Stage.
- **XML_Popup**: The browser popup window opened by clicking Actions → View XML on a Rule.
- **Output_Directory**: The local filesystem directory where XML files are saved.
- **Execution_Log**: A structured log file recording success or failure for each Rule download attempt.
- **Session**: The authenticated browser session maintained by the Downloader.
- **WebDriver**: The Selenium ChromeDriver instance managed by the Downloader.
- **Retry_Mechanism**: Logic that re-attempts a failed operation up to a configurable number of times before marking it as failed.
- **CLI**: The command-line interface through which the Downloader is invoked.
- **Dotenv_File**: A `.env` file containing environment variable definitions loaded at startup.

---

## Requirements

### Requirement 1: Environment Configuration

**User Story:** As a developer, I want to configure the script via environment variables and a `.env` file, so that credentials and settings are not hard-coded and can be changed without modifying source code.

#### Acceptance Criteria

1. THE Downloader SHALL load configuration from a `.env` file at startup using `python-dotenv` when the file is present.
2. THE Downloader SHALL read `PEGA_USERNAME` and `PEGA_PASSWORD` from environment variables.
3. THE Downloader SHALL read `PEGA_URL`, `OUTPUT_DIR`, `HEADLESS`, `MAX_RETRIES`, and `STAGE_LIST` from environment variables, applying documented defaults when a variable is absent.
4. IF `PEGA_USERNAME` or `PEGA_PASSWORD` is absent or empty at startup, THEN THE Downloader SHALL log an ERROR message and exit with a non-zero status code.
5. THE Downloader SHALL accept CLI arguments (`--url`, `--output-dir`, `--headless`, `--max-retries`, `--stages`) that override the corresponding environment variable values when provided.

---

### Requirement 2: Browser Initialization

**User Story:** As a developer, I want the script to launch a controlled Chrome browser session, so that Pega UI interactions are automated reliably.

#### Acceptance Criteria

1. THE Downloader SHALL launch a Chrome browser instance using Selenium WebDriver with ChromeDriver.
2. WHERE `HEADLESS` is set to `true`, THE Downloader SHALL launch Chrome in headless mode.
3. THE Downloader SHALL configure the WebDriver with a page load timeout of 60 seconds and an implicit wait of 0 seconds (explicit waits only).
4. THE Downloader SHALL use `WebDriverWait` with explicit conditions for all element interactions; THE Downloader SHALL NOT use `time.sleep` for synchronization.
5. IF the WebDriver fails to initialize, THEN THE Downloader SHALL log an ERROR message and exit with a non-zero status code.

---

### Requirement 3: Authentication

**User Story:** As a developer, I want the script to log in to Pega automatically, so that the session is established before any navigation begins.

#### Acceptance Criteria

1. WHEN the Downloader starts a session, THE Downloader SHALL navigate to `PEGA_URL`.
2. WHEN the Pega login page is loaded, THE Downloader SHALL enter the value of `PEGA_USERNAME` into the username field and the value of `PEGA_PASSWORD` into the password field, then submit the form.
3. WHEN login succeeds, THE Downloader SHALL log an INFO message confirming successful authentication.
4. IF the login page does not reach an authenticated state within 30 seconds after form submission, THEN THE Downloader SHALL log an ERROR message, capture a screenshot, and exit with a non-zero status code.
5. THE Downloader SHALL use CSS selectors or XPath expressions that do not rely on dynamic or session-specific ID attributes for login form elements.

---

### Requirement 4: Navigation to Dev Studio and Case Type

**User Story:** As a developer, I want the script to navigate to Dev Studio and open the target Case Type, so that the correct rules are accessible for download.

#### Acceptance Criteria

1. WHEN authentication succeeds, THE Downloader SHALL navigate to Dev Studio within the authenticated session.
2. WHEN Dev Studio is loaded, THE Downloader SHALL navigate to the "Case Types" section within Dev Studio.
3. WHEN the Case Types section is loaded, THE Downloader SHALL locate the Case Type named "Tax Compliance Training" in the list.
4. WHEN the "Tax Compliance Training" Case Type is located, THE Downloader SHALL click the "Actions" menu associated with that Case Type and then click "Open" to open the Case Type detail view.
5. IF the Case Type "Tax Compliance Training" is not found in the Case Types list, THEN THE Downloader SHALL log an ERROR message, capture a screenshot, and exit with a non-zero status code.
6. THE Downloader SHALL use element locators that are stable against Pega's dynamic ID generation (e.g., `data-test-id` attributes, stable class names, or text-based XPath).

---

### Requirement 5: Stage and Rule Discovery

**User Story:** As a developer, I want the script to enumerate all rules within each configured stage, so that no rule is missed during the download run.

#### Acceptance Criteria

1. WHEN the Case Type detail view is open, THE Downloader SHALL navigate to the "Stages" section within that view.
2. THE Downloader SHALL iterate over every Stage listed in `STAGE_LIST` in the order they are specified (e.g., Initialization, Primary, Alternatives); THE Downloader SHALL NOT skip any Stage in `STAGE_LIST`.
3. WHEN a Stage is located, THE Downloader SHALL expand or open that Stage to reveal every Rule listed within it; "Program Design" is one example of a Rule that may appear — there may be many other Rules per Stage, and all of them must be discovered.
4. WHEN a Stage is opened, THE Downloader SHALL collect the names and navigation references of ALL Rules listed within that Stage before opening any individual Rule; THE Downloader SHALL NOT begin processing Rules until the complete list for that Stage has been collected.
5. THE Downloader SHALL NOT stop Rule collection for a Stage after finding the first Rule — it SHALL continue collecting until no further Rules remain in that Stage.
6. WHEN all Rules in a Stage have been collected and processed, THE Downloader SHALL move to the next Stage in `STAGE_LIST` and repeat the discovery and processing steps for that Stage.
7. IF a Stage listed in `STAGE_LIST` is not found in the Case Type's Stages section, THEN THE Downloader SHALL log a WARNING message for that Stage and continue processing the remaining stages.
8. THE Downloader SHALL support discovery of at least 1000 Rules across all stages in a single run without exhausting browser memory or producing duplicate entries.
9. WHEN Rule discovery for a Stage is complete, THE Downloader SHALL log an INFO message stating the Stage name and the count of Rules discovered.

---

### Requirement 6: XML Extraction per Rule

**User Story:** As a developer, I want the script to open each rule, extract its XML content via the View XML popup, and save it to a file, so that all rule definitions are captured locally.

#### Acceptance Criteria

1. THE Downloader SHALL execute the XML extraction loop for EVERY Rule discovered in EVERY Stage — no Rule shall be skipped unless it is confirmed as a duplicate (already downloaded per Requirement 8).
2. THE Downloader SHALL process each Rule one by one, in the order it was collected, until all Rules in all Stages have been processed.
3. WHEN a Rule is selected within a Stage, THE Downloader SHALL click the "Actions" menu associated with that Rule and then click "View XML".
4. WHEN the XML_Popup window opens, THE Downloader SHALL switch the WebDriver context to the popup window.
5. WHEN the WebDriver context is on the XML_Popup, THE Downloader SHALL extract the full text content of the XML displayed.
6. WHEN XML content is extracted, THE Downloader SHALL save it to a file in Output_Directory using the naming format `{CaseType}_{Stage}_{RuleName}.xml`, where spaces are replaced with underscores and characters invalid for filenames are removed.
7. WHEN the file is saved, THE Downloader SHALL close the XML_Popup and switch the WebDriver context back to the main window.
8. WHEN a Rule's XML is saved successfully, THE Downloader SHALL log an INFO message with the Rule name and the saved file path.
9. IF the XML_Popup does not open within 15 seconds of clicking "View XML", THEN THE Downloader SHALL invoke the Retry_Mechanism for that Rule.
10. WHEN a Rule fails after all retry attempts, THE Downloader SHALL log an ERROR message for that Rule and continue processing the next Rule; THE Downloader SHALL NOT stop the extraction loop due to a single Rule failure.

---

### Requirement 7: Retry Mechanism

**User Story:** As a developer, I want failed operations to be retried automatically, so that transient UI delays do not cause unnecessary failures.

#### Acceptance Criteria

1. THE Retry_Mechanism SHALL re-attempt a failed Rule extraction up to `MAX_RETRIES` times before marking the Rule as failed.
2. WHEN a retry attempt begins, THE Downloader SHALL log an INFO message stating the Rule name, the attempt number, and the reason for retry.
3. WHEN all retry attempts for a Rule are exhausted without success, THE Downloader SHALL log an ERROR message for that Rule and continue processing the next Rule.
4. THE Retry_Mechanism SHALL apply an exponential back-off delay between attempts, starting at 2 seconds and doubling with each subsequent attempt, up to a maximum of 30 seconds.
5. THE Retry_Mechanism SHALL NOT retry authentication failures or missing Case Type errors, as those are terminal conditions.

---

### Requirement 8: Duplicate Download Prevention

**User Story:** As a developer, I want the script to skip rules that have already been downloaded, so that re-runs do not overwrite existing files or waste time.

#### Acceptance Criteria

1. BEFORE opening a Rule, THE Downloader SHALL check whether a file with the expected output filename already exists in Output_Directory.
2. IF the expected output file already exists, THEN THE Downloader SHALL log an INFO message indicating the Rule was skipped as a duplicate and SHALL NOT re-download it.
3. THE Downloader SHALL maintain an in-memory set of already-processed Rule filenames for the current run to prevent duplicate processing within the same session.

---

### Requirement 9: Failure Screenshot Capture

**User Story:** As a developer, I want screenshots captured automatically on failure, so that I can diagnose UI issues without re-running the script.

#### Acceptance Criteria

1. WHEN any Rule extraction fails after all retry attempts, THE Downloader SHALL capture a screenshot of the current browser state.
2. THE Downloader SHALL save the screenshot to Output_Directory using the naming format `FAILED_{CaseType}_{Stage}_{RuleName}_{timestamp}.png`.
3. WHEN a screenshot is saved, THE Downloader SHALL log an INFO message with the screenshot file path.
4. IF the screenshot capture itself fails, THEN THE Downloader SHALL log a WARNING message and continue processing.

---

### Requirement 10: Execution Log

**User Story:** As a developer, I want a structured execution log recording the outcome of every rule download attempt, so that I can audit results and identify failures after a run.

#### Acceptance Criteria

1. THE Downloader SHALL write an Execution_Log file to Output_Directory upon completion of all processing.
2. THE Execution_Log SHALL contain one entry per Rule processed, including: Rule name, Stage name, output filename, status (success or failure), timestamp, and failure reason (if applicable).
3. THE Execution_Log SHALL be written in JSON Lines format (one JSON object per line) to support streaming and large-scale parsing.
4. WHEN the Downloader exits (normally or due to a terminal error), THE Downloader SHALL flush and close the Execution_Log file before terminating.
5. THE Downloader SHALL log an INFO message upon Execution_Log creation stating the file path and total counts of successful and failed downloads.

---

### Requirement 11: Structured Logging

**User Story:** As a developer, I want all script activity logged at appropriate severity levels with step-verification messages at every navigation and interaction point, so that I can monitor progress, verify each step is working correctly, and diagnose issues during long runs.

#### Acceptance Criteria

1. THE Downloader SHALL use Python's `logging` module with a configurable log level (default: INFO).
2. THE Downloader SHALL emit log messages at INFO level for: session start, login success, stage discovery, rule discovery counts, each successful XML save, each skipped duplicate, and session end summary.
3. THE Downloader SHALL emit log messages at WARNING level for: missing stages, failed screenshot captures, and non-fatal unexpected UI states.
4. THE Downloader SHALL emit log messages at ERROR level for: authentication failure, missing Case Type, unrecoverable rule extraction failures, and WebDriver initialization failure.
5. THE Downloader SHALL include a timestamp, log level, and module name in every log message.
6. THE Downloader SHALL write log output to both stdout and a log file in Output_Directory.
7. WHEN each major navigation step begins, THE Downloader SHALL emit an INFO log message stating the step being attempted (e.g., "Navigating to Dev Studio", "Navigating to Case Types section", "Locating Case Type 'Tax Compliance Training'", "Clicking Actions → Open", "Navigating to Stages section", "Opening stage 'Initialization'", "Selecting rule 'Program Design'", "Clicking Actions → View XML").
8. WHEN each major navigation step completes successfully, THE Downloader SHALL emit an INFO log message confirming the step succeeded (e.g., "Dev Studio loaded successfully", "Case Types section loaded", "Case Type located", "Case Type detail view opened").
9. WHEN any UI element is located by the WebDriver, THE Downloader SHALL emit an INFO log message identifying the element found (e.g., "Found Actions menu for Case Type", "Found 'Open' menu item", "Found 'View XML' menu item").
10. WHEN any UI element is clicked, THE Downloader SHALL emit an INFO log message confirming the click action (e.g., "Clicked Actions menu", "Clicked 'Open'", "Clicked 'View XML'").
11. AT each key navigation checkpoint, THE Downloader SHALL emit an INFO log message stating the current page URL or page title to confirm the browser is at the expected location.
12. WHEN the WebDriver switches to a popup window or back to the main window, THE Downloader SHALL emit an INFO log message stating the direction of the switch and the window handle or title.
13. WHEN rule or stage discovery completes at each step, THE Downloader SHALL emit an INFO log message stating the count of items found (e.g., "Discovered 3 stages", "Discovered 47 rules in stage 'Initialization'").

---

### Requirement 12: Modular Code Design

**User Story:** As a developer, I want the script organized into well-defined modules, so that individual components can be tested, maintained, and extended independently.

#### Acceptance Criteria

1. THE Downloader SHALL be organized into at minimum the following modules: `config` (configuration loading), `browser` (WebDriver lifecycle), `auth` (login logic), `navigator` (Dev Studio and Case Type navigation), `extractor` (Rule XML extraction), `storage` (file I/O and duplicate checking), and `logger` (logging setup).
2. THE Downloader SHALL expose a `main` entry point that orchestrates the modules in sequence.
3. THE Downloader SHALL be executable as a CLI script via `python -m pega_xml_downloader` or a named entry point.
4. WHEN any module raises an unhandled exception, THE Downloader SHALL catch it at the `main` level, log an ERROR message with the traceback, capture a screenshot if the WebDriver is active, and exit with a non-zero status code.

---

### Requirement 13: Output File Management

**User Story:** As a developer, I want output files organized predictably, so that I can locate and use downloaded XML files easily.

#### Acceptance Criteria

1. THE Downloader SHALL create Output_Directory and any required subdirectories at startup if they do not already exist.
2. THE Downloader SHALL save each XML file using the naming format `{CaseType}_{Stage}_{RuleName}.xml` with spaces replaced by underscores and filesystem-unsafe characters removed.
3. THE Downloader SHALL write XML files using UTF-8 encoding.
4. IF writing an XML file fails due to a filesystem error, THEN THE Downloader SHALL log an ERROR message for that Rule, record the failure in the Execution_Log, and continue processing the next Rule.

---

### Requirement 14: Parallel Download Support (Optional)

**User Story:** As a developer, I want the option to download rules in parallel, so that large rule sets can be processed faster when system resources allow.

#### Acceptance Criteria

1. WHERE `PARALLEL_WORKERS` is set to a value greater than 1, THE Downloader SHALL use a thread pool with at most `PARALLEL_WORKERS` concurrent browser sessions to download Rules simultaneously.
2. WHILE parallel downloads are active, THE Downloader SHALL ensure that file writes and Execution_Log entries are thread-safe.
3. WHERE `PARALLEL_WORKERS` is set to 1 or is absent, THE Downloader SHALL execute downloads sequentially.
4. THE Downloader SHALL log an INFO message at startup stating the number of parallel workers configured.

---

### Requirement 15: Deliverables and Setup

**User Story:** As a developer, I want complete setup instructions and dependency files, so that I can install and run the script in a new environment without guesswork.

#### Acceptance Criteria

1. THE Downloader SHALL include a `requirements.txt` file listing all Python dependencies with pinned versions.
2. THE Downloader SHALL include a `.env.example` file documenting all supported environment variables with example values and descriptions.
3. THE Downloader SHALL include a `README.md` file with: prerequisites, installation steps, configuration reference, usage examples (basic and CLI), and output structure description.
4. THE Downloader SHALL be compatible with Python 3.10 or later.

---

### Requirement 16: Complete Stage Exhaustion

**User Story:** As a developer, I want the script to process every rule in every stage without stopping early, so that no rule XML is missed across the entire case type.

#### Acceptance Criteria

1. THE Downloader SHALL process all Rules in a Stage before moving to the next Stage in `STAGE_LIST`; THE Downloader SHALL NOT advance to the next Stage while any unprocessed Rule remains in the current Stage.
2. THE Downloader SHALL process all Stages in `STAGE_LIST` before completing the run; THE Downloader SHALL NOT exit or terminate the stage loop until every Stage has been attempted.
3. WHEN all Rules in a Stage have been processed, THE Downloader SHALL log an INFO message stating the Stage name and the total count of Rules processed in that Stage.
4. WHEN all Stages in `STAGE_LIST` have been processed, THE Downloader SHALL log an INFO summary message stating: total stages processed, total rules processed across all stages, total successful downloads, and total failed downloads.
5. IF a single Rule extraction fails after all retry attempts, THEN THE Downloader SHALL log an ERROR message for that Rule and continue to the next Rule; THE Downloader SHALL NOT exit the extraction loop due to a single Rule failure.
