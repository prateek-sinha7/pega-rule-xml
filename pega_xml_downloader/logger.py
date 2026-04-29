"""Logging setup for the Pega XML Downloader.

Configures dual-output logging (stdout + file) with a configurable level.
"""

import logging
import os
import sys


def setup_logging(log_level: str, output_dir: str) -> logging.Logger:
    """Configure root logger with stdout and file handlers.

    Sets up the root logger with:
    - A StreamHandler writing to stdout
    - A FileHandler writing to {output_dir}/downloader.log

    Both handlers use the format:
        %(asctime)s - %(levelname)s - %(name)s - %(message)s

    Args:
        log_level: Python logging level string (e.g. "INFO", "DEBUG", "WARNING").
        output_dir: Directory where the log file will be written.
            Created if it does not already exist.

    Returns:
        The configured root logger instance.
    """
    # Ensure the output directory exists before creating the FileHandler
    os.makedirs(output_dir, exist_ok=True)

    # Resolve the numeric log level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Get the root logger and set its level
    logger = logging.getLogger()
    logger.setLevel(numeric_level)

    # Define the shared format
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )

    # StreamHandler for stdout
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(numeric_level)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # FileHandler for {output_dir}/downloader.log
    log_file_path = os.path.join(output_dir, "downloader.log")
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
