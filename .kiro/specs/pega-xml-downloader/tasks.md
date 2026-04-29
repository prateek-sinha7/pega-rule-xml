# Implementation Plan: Pega XML Downloader

## Overview

This plan implements a Python CLI tool that uses Selenium to automate XML extraction from the Pega Platform UI. The implementation follows the pipeline architecture defined in the design: config → logger → browser → auth → navigator → extractor → storage → main orchestrator. Each task builds incrementally, with modules wired together at the end.

## Tasks

- [x] 1. Set up project structure, dependencies, and package scaffolding
  - Create the `pega_xml_downloader/` package directory with `__init__.py`
  - Create `pega_xml_downloader/__main__.py` entry point that calls `main()` and exits with its return code
  - Create `requirements.txt` with pinned versions: `selenium`, `python-dotenv`, and any other required dependencies
  - Create `.env.example` documenting all supported environment variables (`PEGA_URL`, `PEGA_USERNAME`, `PEGA_PASSWORD`, `OUTPUT_DIR`, `HEADLESS`, `MAX_RETRIES`, `STAGE_LIST`, `PARALLEL_WORKERS`, `LOG_LEVEL`) with example values and descriptions
  - _Requirements: 15.1, 15.2, 15.4, 12.3_

- [ ] 2. Implement the `config` module
  - [x] 2.1 Create `pega_xml_downloader/config.py` with the `AppConfig` frozen dataclass
    - Define all fields: `pega_url`, `pega_username`, `pega_password`, `output_dir`, `headless`, `max_retries`, `stage_list`, `parallel_workers`, `log_level`, `case_type_name` with documented defaults
    - _Requirements: 1.3_

  - [x] 2.2 Implement `parse_cli_args()` using `argparse`
    - Support `--url`, `--output-dir`, `--headless`, `--max-retries`, `--stages` arguments
    - Return a dict of only the arguments that were explicitly provided
    - _Requirements: 1.5_

  - [x] 2.3 Implement `load_config()` with precedence: CLI args > env vars > .env file > defaults
    - Load `.env` file using `python-dotenv` when present
    - Read all environment variables and merge with CLI args
    - Validate that `PEGA_USERNAME` and `PEGA_PASSWORD` are present and non-empty; log ERROR and `sys.exit(1)` if missing
    - Parse `STAGE_LIST` from comma-separated string to list
    - Parse `HEADLESS` from string to bool
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 2.4 Implement `sanitize_filename()` utility
    - Replace spaces with underscores, remove filesystem-unsafe characters
    - _Requirements: 6.6, 13.2_

  - [ ]* 2.5 Write unit tests for the `config` module
    - Test `load_config` with various combinations of env vars, CLI args, and defaults
    - Test missing required credentials triggers exit
    - Test `sanitize_filename` with edge cases (special characters, spaces, empty strings)
    - Test CLI arg precedence over env vars
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ] 3. Implement the `logger` module
  - [x] 3.1 Create `pega_xml_downloader/logger.py` with `setup_logging()` function
    - Configure root logger with configurable log level
    - Add `StreamHandler` for stdout output
    - Add `FileHandler` writing to `{output_dir}/downloader.log`
    - Set format: `%(asctime)s - %(levelname)s - %(name)s - %(message)s`
    - Return the configured logger
    - _Requirements: 11.1, 11.5, 11.6_

  - [ ]* 3.2 Write unit tests for the `logger` module
    - Test that both handlers are attached
    - Test log level configuration
    - Test log message format includes timestamp, level, and module name
    - _Requirements: 11.1, 11.5, 11.6_

- [ ] 4. Implement the `storage` module
  - [x] 4.1 Create `pega_xml_downloader/storage.py` with `LogEntry` dataclass and `StorageManager` class
    - Define `LogEntry` with fields: `rule_name`, `stage_name`, `output_filename`, `status`, `timestamp`, `failure_reason`
    - Implement `__init__` with output_dir, case_type_name, in-memory processed set, and log entries list
    - _Requirements: 10.2_

  - [x] 4.2 Implement `ensure_output_dir()` to create output directory if it doesn't exist
    - _Requirements: 13.1_

  - [x] 4.3 Implement `build_filename()` using `sanitize_filename` from config module
    - Format: `{CaseType}_{Stage}_{RuleName}.xml` with spaces replaced by underscores
    - _Requirements: 6.6, 13.2_

  - [x] 4.4 Implement `is_duplicate()` checking both filesystem and in-memory set
    - _Requirements: 8.1, 8.3_

  - [x] 4.5 Implement `save_xml()` writing UTF-8 encoded XML content and updating the processed set
    - _Requirements: 13.3, 8.3_

  - [x] 4.6 Implement `record_result()` and `write_execution_log()` in JSON Lines format
    - Write one JSON object per line to `{output_dir}/execution_log.jsonl`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 4.7 Implement `get_summary()` returning total, successful, and failed counts
    - _Requirements: 10.5, 16.4_

  - [ ]* 4.8 Write unit tests for the `storage` module
    - Test `build_filename` produces correct format
    - Test `is_duplicate` with filesystem and in-memory checks
    - Test `save_xml` writes correct content with UTF-8 encoding
    - Test `write_execution_log` produces valid JSON Lines
    - Test `get_summary` counts
    - _Requirements: 8.1, 8.2, 8.3, 10.1, 10.2, 10.3, 13.2, 13.3_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement the `browser` module
  - [x] 6.1 Create `pega_xml_downloader/browser.py` with `create_driver()` function
    - Configure Chrome with headless mode based on `config.headless`
    - Set page load timeout to 60 seconds, implicit wait to 0 seconds
    - Log ERROR and `sys.exit(1)` on initialization failure
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [x] 6.2 Implement `capture_screenshot()` function
    - Save screenshot to `{output_dir}/FAILED_{label}_{timestamp}.png`
    - Return file path on success, None on failure
    - Log WARNING if screenshot capture itself fails
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 6.3 Implement `switch_to_popup()` and `switch_to_main()` window management functions
    - `switch_to_popup`: Wait for new window handle with configurable timeout (default 15s), switch to it
    - `switch_to_main`: Close current window, switch back to main window handle
    - Log INFO messages for window switches with handle/title info
    - _Requirements: 6.4, 6.7, 11.12_

  - [x] 6.4 Implement `quit_driver()` for safe WebDriver cleanup
    - Log any errors during quit
    - _Requirements: 2.1_

  - [ ]* 6.5 Write unit tests for the `browser` module
    - Test `capture_screenshot` file naming and error handling
    - Test `switch_to_popup` timeout behavior
    - Test `switch_to_main` closes popup and switches back
    - _Requirements: 2.1, 2.2, 2.3, 9.1, 9.2, 9.3, 9.4_

- [ ] 7. Implement the `auth` module
  - [x] 7.1 Create `pega_xml_downloader/auth.py` with `AuthenticationError` exception and `login()` function
    - Navigate to `PEGA_URL`
    - Enter username and password using stable selectors (no dynamic IDs)
    - Submit login form
    - Wait up to 30 seconds for authenticated state using `WebDriverWait`
    - Log INFO on success, log ERROR + capture screenshot + raise `AuthenticationError` on failure
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 2.4, 11.7, 11.8, 11.9, 11.10_

  - [ ]* 7.2 Write unit tests for the `auth` module
    - Test successful login flow with mocked WebDriver
    - Test timeout raises `AuthenticationError`
    - Test screenshot is captured on failure
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 8. Implement the `navigator` module
  - [x] 8.1 Create `pega_xml_downloader/navigator.py` with `RuleRef` dataclass and `NavigationError` exception
    - Define `RuleRef` with fields: `name`, `stage_name`, `locator`, `index`
    - _Requirements: 5.3_

  - [x] 8.2 Implement `navigate_to_case_type()` function
    - Navigate from authenticated session to Dev Studio → Case Types → locate target → Actions → Open
    - Use stable element locators (not dynamic IDs)
    - Log INFO at each navigation step (entering Dev Studio, locating Case Type, clicking Actions, clicking Open)
    - Log INFO confirming each step succeeded with current URL/title
    - Raise `NavigationError` with screenshot if Case Type not found
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 11.7, 11.8, 11.9, 11.10, 11.11_

  - [x] 8.3 Implement `discover_stages()` function
    - Identify which stages from `stage_list` are present in the Case Type detail view
    - Log WARNING for any stage not found
    - Log INFO with count of discovered stages
    - _Requirements: 5.1, 5.7, 5.9, 11.13_

  - [x] 8.4 Implement `discover_rules()` function
    - Open/expand a stage and collect ALL rule references before returning
    - Collect complete list using collect-then-process pattern
    - Support discovery of 1000+ rules without memory issues
    - Log INFO with stage name and rule count when discovery completes
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.8, 5.9, 11.13_

  - [ ]* 8.5 Write unit tests for the `navigator` module
    - Test `navigate_to_case_type` step sequence with mocked WebDriver
    - Test `NavigationError` raised when Case Type not found
    - Test `discover_stages` handles missing stages with warnings
    - Test `discover_rules` collects all rules before returning
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.7_

- [ ] 9. Implement the `extractor` module
  - [x] 9.1 Create `pega_xml_downloader/extractor.py` with `ExtractionResult` dataclass and `ExtractionError` exception
    - Define `ExtractionResult` with fields: `rule_ref`, `success`, `xml_content`, `error_message`, `attempts`
    - _Requirements: 6.5_

  - [x] 9.2 Implement `_attempt_extraction()` for a single extraction attempt
    - Click Actions → View XML on the rule
    - Switch to popup window using `browser.switch_to_popup()`
    - Extract full XML text content from the popup
    - Close popup and return to main window using `browser.switch_to_main()`
    - Log INFO messages for each UI interaction (finding menu, clicking, switching windows)
    - Raise `ExtractionError` on failure
    - _Requirements: 6.3, 6.4, 6.5, 6.7, 11.9, 11.10, 11.12_

  - [x] 9.3 Implement `extract_rule_xml()` with retry logic and exponential backoff
    - Retry up to `max_retries` times on failure
    - Exponential backoff: 2s, 4s, 8s... capped at 30s
    - Log INFO on each retry attempt with rule name, attempt number, and reason
    - Log ERROR when all retries exhausted
    - Do NOT retry authentication failures or missing Case Type errors
    - Return `ExtractionResult` with success/failure details and attempt count
    - _Requirements: 6.9, 6.10, 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 9.4 Write unit tests for the `extractor` module
    - Test successful extraction flow
    - Test retry logic with exponential backoff timing
    - Test max retries exhaustion returns failure result
    - Test non-retryable errors are not retried
    - _Requirements: 6.3, 6.4, 6.5, 6.9, 6.10, 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement the `main` orchestrator and wire all modules together
  - [x] 11.1 Create `pega_xml_downloader/main.py` with `main()` function
    - Load config via `parse_cli_args()` and `load_config()`
    - Set up logging via `setup_logging()`
    - Create output directory via `StorageManager.ensure_output_dir()`
    - Log INFO at startup with parallel workers count
    - _Requirements: 1.1, 1.5, 12.2, 14.4_

  - [x] 11.2 Implement browser launch, authentication, and navigation sequence in `main()`
    - Create WebDriver via `create_driver()`
    - Store main window handle
    - Call `login()` for authentication
    - Call `navigate_to_case_type()` to reach the Case Type detail view
    - _Requirements: 2.1, 3.1, 4.1_

  - [x] 11.3 Implement the stage and rule processing loop in `main()`
    - Call `discover_stages()` to find available stages
    - For each stage: call `discover_rules()`, then for each rule:
      - Check `is_duplicate()` and skip with INFO log if already downloaded
      - Call `extract_rule_xml()` for new rules
      - On success: `save_xml()` and `record_result()` with success entry, log INFO with file path
      - On failure: `capture_screenshot()`, `record_result()` with failure entry, log ERROR
      - Handle filesystem write errors: log ERROR, record failure, continue to next rule
    - Process ALL rules in a stage before moving to the next stage
    - Process ALL stages before completing
    - Log INFO with stage name and rule count after each stage completes
    - _Requirements: 5.2, 5.6, 6.1, 6.2, 6.6, 6.8, 6.10, 8.1, 8.2, 9.1, 9.2, 9.3, 11.2, 11.3, 11.4, 13.4, 16.1, 16.2, 16.3, 16.5_

  - [x] 11.4 Implement cleanup and exit logic in `main()`
    - Write execution log via `write_execution_log()`
    - Log INFO summary: total stages, total rules, successful downloads, failed downloads
    - Quit WebDriver via `quit_driver()`
    - Catch all unhandled exceptions at the `main` level: log ERROR with traceback, capture screenshot if driver active, exit non-zero
    - Return 0 if all rules succeeded, 1 if any failures
    - _Requirements: 10.1, 10.4, 10.5, 12.4, 16.4_

  - [ ]* 11.5 Write integration tests for the `main` orchestrator
    - Test full pipeline with mocked Selenium WebDriver
    - Test graceful handling of authentication failure
    - Test graceful handling of navigation failure
    - Test that partial failures don't stop the run
    - Test execution log is written even on early termination
    - _Requirements: 12.2, 12.4, 16.1, 16.2, 16.4, 16.5_

- [ ] 12. Implement optional parallel download support
  - [x] 12.1 Add parallel execution mode to `main()` when `PARALLEL_WORKERS > 1`
    - Use a thread pool with at most `PARALLEL_WORKERS` concurrent browser sessions
    - Ensure thread-safe file writes and execution log entries (use threading locks in `StorageManager`)
    - Fall back to sequential mode when `PARALLEL_WORKERS` is 1 or absent
    - _Requirements: 14.1, 14.2, 14.3_

  - [ ]* 12.2 Write unit tests for parallel execution
    - Test thread-safe file writes under concurrent access
    - Test thread-safe execution log recording
    - Test sequential fallback when workers = 1
    - _Requirements: 14.1, 14.2, 14.3_

- [x] 13. Create README.md and finalize deliverables
  - Create `README.md` with: prerequisites (Python 3.10+, Chrome, ChromeDriver), installation steps, configuration reference for all env vars and CLI args, usage examples (basic and CLI with overrides), and output structure description
  - Verify `.env.example` is complete and accurate
  - Verify `requirements.txt` has all dependencies with pinned versions
  - _Requirements: 15.1, 15.2, 15.3, 15.4_

- [x] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirement clauses for traceability
- Checkpoints ensure incremental validation between major implementation phases
- The design uses explicit waits only (no `time.sleep`) — all Selenium interactions must use `WebDriverWait` with expected conditions
- The collect-then-process pattern in rule discovery is critical to avoid DOM mutation issues
- All modules use Python's `logging` module; verbose step-verification logging is required per Requirement 11
