"""
Logging module for scanning diagnostics.

Usage:
    from scan_logger import get_logger
    log = get_logger(__name__)
    log.info("Message")
    log.debug("Detailed info", extra={"key": "value"})
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Log file location
LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOG_DIR / f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Global flag to check if logging is initialized
_initialized = False


class ScanFormatter(logging.Formatter):
    """Custom formatter with color support for console and detailed file output."""

    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m',
    }

    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S.%f')[:-3]
        level = record.levelname
        name = record.name.split('.')[-1][:15].ljust(15)
        message = record.getMessage()

        # Add extra context if present
        extras = []
        for key, value in record.__dict__.items():
            if key not in ('name', 'msg', 'args', 'created', 'filename', 'funcName',
                          'levelname', 'levelno', 'lineno', 'module', 'msecs',
                          'pathname', 'process', 'processName', 'relativeCreated',
                          'stack_info', 'exc_info', 'exc_text', 'message', 'thread',
                          'threadName', 'taskName'):
                extras.append(f"{key}={value}")

        extra_str = f" [{', '.join(extras)}]" if extras else ""

        if self.use_colors and sys.stderr.isatty():
            color = self.COLORS.get(level, '')
            reset = self.COLORS['RESET']
            return f"{timestamp} {color}{level:8}{reset} {name} | {message}{extra_str}"
        else:
            return f"{timestamp} {level:8} {name} | {message}{extra_str}"


def init_logging(
    level: int = logging.DEBUG,
    console: bool = True,
    file: bool = True,
) -> None:
    """Initialize the logging system."""
    global _initialized
    if _initialized:
        return

    # Create logs directory
    LOG_DIR.mkdir(exist_ok=True)

    # Root logger for scan-related modules
    root = logging.getLogger("scan")
    root.setLevel(level)
    root.handlers.clear()

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(ScanFormatter(use_colors=True))
        root.addHandler(console_handler)

    if file:
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        file_handler.setFormatter(ScanFormatter(use_colors=False))
        root.addHandler(file_handler)

        # Log startup info
        root.info(f"=== Scan session started ===")
        root.info(f"Log file: {LOG_FILE}")
        root.info(f"Python: {sys.version}")
        root.info(f"Platform: {sys.platform}")

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given module name."""
    if not _initialized:
        init_logging()

    # Prefix with 'scan.' for consistent hierarchy
    if not name.startswith("scan."):
        name = f"scan.{name}"

    return logging.getLogger(name)


def log_exception(logger: logging.Logger, exc: Exception, context: str = "") -> None:
    """Log an exception with full traceback."""
    import traceback
    tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if context:
        logger.error(f"{context}: {exc}\n{tb}")
    else:
        logger.error(f"Exception: {exc}\n{tb}")


# Convenience function to get the log file path
def get_log_file() -> Path:
    """Return the current log file path."""
    return LOG_FILE
