# Bookget - Download ancient Chinese book resources from digital libraries

from .config import Config
from .exceptions import GujiResourceError

# Keep in sync with [project] version in pyproject.toml.
__version__ = "0.4.0"
__all__ = ["Config", "GujiResourceError"]
