"""Page extractor package: browser-driven DOM snapshot extraction and filtering."""

from . import constants
from .browser_session import BrowserSession
from .html_builder import HtmlBuilder
from .modification_rules import (
    CleanEmpty,
    CollapseWrappers,
    CompactInteractible,
    KeepAttrs,
    MarkInteractible,
    Rule,
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
    "CollapseWrappers",
    "CompactInteractible",
    "ExtractionResult",
    "HtmlBuilder",
    "KeepAttrs",
    "MarkInteractible",
    "OutputConfig",
    "OutputWriter",
    "PageExtractor",
    "Rule",
    "SnapshotParser",
    "StripTags",
    "UnwrapHidden",
    "UnwrapUnkept",
    "constants",
]
