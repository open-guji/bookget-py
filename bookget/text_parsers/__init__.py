"""Text parsers for converting adapter raw data to structured JSON."""

from .base import StructuredText, BaseTextParser
from .shidianguji_parser import ShidianGujiParser
from .hanchi_parser import HanchiParser

__all__ = ["StructuredText", "BaseTextParser", "ShidianGujiParser", "HanchiParser"]
