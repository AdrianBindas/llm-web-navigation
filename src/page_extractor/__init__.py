"""Page extractor package: browser-driven DOM snapshot extraction and filtering."""

from . import constants
from .browser_session import BrowserSession
from .html_builder import HtmlBuilder
from .modification_rules import (
    CleanEmpty,
    KeepAttrs,
    Rule,
    StripInternalAttrs,
    StripTags,
    UnwrapHidden,
    UnwrapUnkept,
)
from .page_extractor import (
    ExtractionResult,
    OutputConfig,
    OutputWriter,
    PageExtractor,
)
from .snapshot_parser import SnapshotParser

__all__ = [
    "BrowserSession",
    "CleanEmpty",
    "ExtractionResult",
    "HtmlBuilder",
    "KeepAttrs",
    "OutputConfig",
    "OutputWriter",
    "PageExtractor",
    "Rule",
    "SnapshotParser",
    "StripInternalAttrs",
    "StripTags",
    "UnwrapHidden",
    "UnwrapUnkept",
    "constants",
]
