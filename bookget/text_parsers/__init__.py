"""Text parsers for converting adapter raw data to structured JSON."""

from .base import StructuredText, BaseTextParser
from .shidianguji_parser import ShidianGujiParser

__all__ = ["StructuredText", "BaseTextParser", "ShidianGujiParser"]
