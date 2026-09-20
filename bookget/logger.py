# Logging setup for Guji Resource Manager

import logging
import sys

# Create logger
logger = logging.getLogger("bookget")


def _utf8_console_stream():
    """Return a UTF-8 stream for console logging, or None if there is none.

    Returns None in a windowed build (no console, no redirect), where
    sys.stdout is None. Also tolerates streams that exist but have no real
    file descriptor behind them, which `fileno()` reports by raising.
    """
    stream = sys.stdout
    if stream is None:
        return None
    try:
        if getattr(stream, "encoding", None) == "utf-8":
            return stream
        return open(stream.fileno(), mode="w", encoding="utf-8",
                    closefd=False, newline="")
    except Exception:
        # No usable fd (redirected to a pipe we can't reopen, etc.) — fall
        # back to the original stream rather than losing logging entirely.
        return stream


def setup_logger(debug: bool = False, log_file: str = None):
    """Configure the logger with appropriate handlers."""
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler (force UTF-8 on Windows to avoid cp1252 encoding errors).
    #
    # In a PyInstaller *windowed* build (console=False, i.e. bookget-ui.exe
    # double-clicked) sys.stdout is None — there is no console and no redirect.
    # Touching sys.stdout.encoding / .fileno() unguarded raised
    #   AttributeError: 'NoneType' object has no attribute 'encoding'
    # before the server ever started, so the app died with a "Fatal error"
    # dialog. There is simply nowhere to log to in that case; skip the console
    # handler instead of crashing.
    stream = _utf8_console_stream()
    if stream is not None:
        console_handler = logging.StreamHandler(stream)
        console_handler.setLevel(level)
        console_format = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        )
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)
    else:
        # Keep logging calls cheap and silent rather than letting the root
        # logger's lastResort handler write to a stderr that isn't there.
        logger.addHandler(logging.NullHandler())

    # File handler (if specified)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger
