"""Storage module for file I/O, duplicate detection, and execution log management.

Handles XML file saving, duplicate prevention (filesystem + in-memory),
and structured execution logging in JSON Lines format.
Thread-safe: uses threading locks to protect shared state when parallel
workers are active.
"""

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Set

from pega_xml_downloader.config import sanitize_filename

logger = logging.getLogger(__name__)


@dataclass
class LogEntry:
    """Single entry in the execution log.

    Fields:
        rule_name: Name of the rule processed.
        stage_name: Name of the parent stage.
        output_filename: Expected output filename.
        status: "success" or "failure".
        timestamp: ISO 8601 timestamp string.
        failure_reason: Error description if failed, None otherwise.
    """

    rule_name: str
    stage_name: str
    output_filename: str
    status: str  # "success" or "failure"
    timestamp: str  # ISO 8601
    failure_reason: Optional[str] = None


class StorageManager:
    """Manages file output, dedup tracking, and execution logging."""

    def __init__(self, output_dir: str, case_type_name: str):
        """Initialize StorageManager.

        Args:
            output_dir: Directory path for all output files.
            case_type_name: Target Case Type name used in filename construction.
        """
        self._output_dir = output_dir
        self._case_type_name = case_type_name
        self._processed: Set[str] = set()
        self._log_entries: List[LogEntry] = []
        self._lock = threading.Lock()

    def ensure_output_dir(self) -> None:
        """Create output directory if it doesn't exist."""
        os.makedirs(self._output_dir, exist_ok=True)
        logger.info("Output directory ensured: %s", self._output_dir)

    def build_filename(self, stage_name: str, rule_name: str) -> str:
        """Build a sanitized filename for a rule's XML output.

        Format: {CaseType}_{Stage}_{RuleName}.xml
        Spaces are replaced with underscores and unsafe characters are removed.

        Args:
            stage_name: Name of the stage containing the rule.
            rule_name: Name of the rule.

        Returns:
            A filesystem-safe filename string.
        """
        case_part = sanitize_filename(self._case_type_name)
        stage_part = sanitize_filename(stage_name)
        rule_part = sanitize_filename(rule_name)
        return f"{case_part}_{stage_part}_{rule_part}.xml"

    def is_duplicate(self, filename: str) -> bool:
        """Check if a file has already been downloaded.

        Checks both the filesystem (for files from previous runs) and the
        in-memory processed set (for files from the current run).
        Thread-safe: acquires lock before checking the processed set.

        Args:
            filename: The filename to check.

        Returns:
            True if the file already exists or has been processed this session.
        """
        with self._lock:
            if filename in self._processed:
                return True
        file_path = os.path.join(self._output_dir, filename)
        return os.path.exists(file_path)

    def save_xml(self, filename: str, content: str) -> str:
        """Write XML content to a file with UTF-8 encoding.

        Adds the filename to the in-memory processed set after successful write.
        Thread-safe: acquires lock for file write and processed set update.

        Args:
            filename: The output filename.
            content: The XML content to write.

        Returns:
            The full file path of the saved file.

        Raises:
            IOError: If the filesystem write fails.
        """
        file_path = os.path.join(self._output_dir, filename)
        with self._lock:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            self._processed.add(filename)
        logger.info("Saved XML file: %s", file_path)
        return file_path

    def record_result(self, entry: LogEntry) -> None:
        """Add a log entry to the in-memory execution log.

        Thread-safe: acquires lock before appending to the log entries list.

        Args:
            entry: The LogEntry to record.
        """
        with self._lock:
            self._log_entries.append(entry)

    def write_execution_log(self) -> str:
        """Write all log entries to execution_log.jsonl in JSON Lines format.

        Each line is a self-contained JSON object representing one LogEntry.

        Returns:
            The full file path of the execution log.
        """
        log_path = os.path.join(self._output_dir, "execution_log.jsonl")
        with open(log_path, "w", encoding="utf-8") as f:
            for entry in self._log_entries:
                line = json.dumps(asdict(entry), ensure_ascii=False)
                f.write(line + "\n")
        logger.info("Execution log written: %s", log_path)
        return log_path

    def get_summary(self) -> Dict[str, int]:
        """Return summary counts of processed rules.

        Returns:
            A dict with keys: total_rules, successful, failed.
        """
        total = len(self._log_entries)
        successful = sum(1 for e in self._log_entries if e.status == "success")
        failed = sum(1 for e in self._log_entries if e.status == "failure")
        return {
            "total_rules": total,
            "successful": successful,
            "failed": failed,
        }
