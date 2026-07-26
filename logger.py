import logging
import sys

def setup_logger() -> logging.Logger:
    """Sets up and returns a custom logger with specific formatting."""
    logger = logging.getLogger("VoiceKeeper")
    logger.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Custom formatter mimicking requested output ([INFO] Message)
    formatter = logging.Formatter('[%(levelname)s] %(message)s')
    console_handler.setFormatter(formatter)

    # Avoid duplicate logs if setup_logger is called multiple times
    if not logger.handlers:
        logger.addHandler(console_handler)

    return logger

# Global logger instance
logger = setup_logger()
