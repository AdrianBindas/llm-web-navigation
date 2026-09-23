"""Module-level constants for the page extractor pipeline."""

from pathlib import Path

# Repo root, resolved from this file's location (src/page_extractor/constants.py),
# so output paths do not depend on the current working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Default output locations, anchored to the project root.
OUTPUT_DIR = PROJECT_ROOT
IMAGES_DIR = PROJECT_ROOT / "images"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# --- Parser-level constants ------------------------------------------------
# These describe how to read the snapshot, not what to filter.

# Computed styles requested from the snapshot. Must match the set passed to
# DOMSnapshot.captureSnapshot. The styles map is resolved by key name.
COMPUTED_STYLE_KEYS = ["display", "visibility", "opacity", "cursor", "background-image"]

VIEWPORT = {"width": 1280, "height": 800}

# CDP DOM node type constants.
ELEMENT_NODE = 1
TEXT_NODE = 3
DOCUMENT_NODE = 9


# --- Default filter data ---------------------------------------------------
# These sets are the defaults baked into the built-in rules. All decisions about
# what is kept, dropped, or unwrapped live in the rules, not in the parser.

# Tags that should be stripped entirely (subtree removed).
STRIP_TAGS = {
    "script", "style", "link", "meta", "noscript", "head",
    "svg", "path", "symbol", "defs", "use",
    "iframe", "object", "embed", "applet",
}

# Attributes that keep meaningful information.
KEEP_ATTRS = {
    "href", "src", "alt", "title", "aria-label", "role",
    "type", "name", "placeholder", "value", "action",
    "data-visible", "data-bounds",
}

# Tags that are inherently interactible.
INTERACTIVE_TAGS = {
    "a", "button", "input", "select", "textarea",
    "option", "label", "summary", "details",
    "form", "fieldset",
}

# ARIA roles that mark an element as interactible.
INTERACTIVE_ROLES = {
    "button", "link", "checkbox", "radio", "tab", "menuitem",
    "menuitemcheckbox", "menuitemradio", "switch", "option",
    "combobox", "slider", "searchbox", "textbox",
    "search", "spinbutton", "menu", "menubar", "listbox",
    "tablist", "treeitem",
}

# Tags whose presence counts as direct visual content.
MEDIA_TAGS = {"img", "video", "canvas", "audio"}

# Maximum length of a kept attribute value; longer values are truncated to keep
# script-in-attribute noise out of the dump.
MAX_ATTR_LEN = 120
