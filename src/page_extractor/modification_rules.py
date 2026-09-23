"""A rule is a callable object: rule(soup, parser) -> BeautifulSoup. Rules edit
the tree in place (and return it). They query snapshot signals through the
parser via each tag's 'data-node-id' attribute. Rules are modular: reorder,
remove, or add your own to a FilterConfig.rules list."""

import logging

from bs4 import Comment

from .constants import (
    ELEMENT_NODE,
    INTERACTIVE_ROLES,
    INTERACTIVE_TAGS,
    KEEP_ATTRS,
    MAX_ATTR_LEN,
    MEDIA_TAGS,
    STRIP_TAGS,
    TEXT_NODE,
)

logger = logging.getLogger(__name__)


def node_id_of(tag):
    """Read the parser node id off a soup tag, or None if absent/invalid."""
    raw = tag.get("data-node-id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class Rule:
    """Base class for a tree-editing rule. Subclasses implement __call__."""

    def __call__(self, soup, parser):
        return soup


class StripTags(Rule):
    """Remove elements whose tag is in the strip set, along with their subtree."""

    def __init__(self, tags=None):
        self.tags = set(tags) if tags is not None else set(STRIP_TAGS)

    def __call__(self, soup, parser):
        for tag in soup.find_all(self.tags):
            tag.decompose()
        return soup


class UnwrapHidden(Rule):
    """Unwrap elements the parser marks as not visible, promoting their children."""

    def __call__(self, soup, parser):
        for tag in soup.find_all(True):
            nid = node_id_of(tag)
            if nid is not None and not parser.is_visible(nid):
                tag.unwrap()
        return soup


class UnwrapUnkept(Rule):
    """
    Unwrap visible elements that are neither interactible nor bear direct
    content. Their qualifying descendants are promoted; pure wrappers vanish.

    This rule owns the definition of "interactible" and "content": an element is
    interactible if its tag is in interactive_tags, its role is in
    interactive_roles, or its computed cursor is 'pointer'; it bears content if
    it is a media tag, has a direct media child, has a direct non-empty text
    node, or renders a CSS background-image. Only structural signals come from
    the parser (tag, attrs, styles, children).
    """

    def __init__(self, interactive_tags=None, interactive_roles=None, media_tags=None):
        self.interactive_tags = (
            set(interactive_tags) if interactive_tags is not None else set(INTERACTIVE_TAGS)
        )
        self.interactive_roles = (
            set(interactive_roles) if interactive_roles is not None else set(INTERACTIVE_ROLES)
        )
        self.media_tags = set(media_tags) if media_tags is not None else set(MEDIA_TAGS)

    def is_interactible(self, parser, node_id):
        tag = parser.tag_of(node_id)
        if tag in self.interactive_tags:
            return True
        role = parser.get_attr(node_id, "role").lower()
        if role in self.interactive_roles:
            return True
        return parser.styles_of(node_id).get("cursor") == "pointer"

    def has_direct_content(self, parser, node_id):
        tag = parser.tag_of(node_id)
        if tag in self.media_tags:
            return True
        bg = parser.styles_of(node_id).get("background-image", "")
        if bg and bg != "none":
            return True
        for child in parser.children[node_id]:
            if parser.type_of(child) == TEXT_NODE and parser.text_of(child).strip():
                return True
            if parser.type_of(child) == ELEMENT_NODE and parser.tag_of(child) in self.media_tags:
                return True
        return False

    def __call__(self, soup, parser):
        # Bottom-up so that unwrapping a parent does not disturb child iteration.
        for tag in reversed(soup.find_all(True)):
            nid = node_id_of(tag)
            if nid is None:
                continue
            if self.is_interactible(parser, nid) or self.has_direct_content(parser, nid):
                continue
            tag.unwrap()
        return soup


class KeepAttrs(Rule):
    """
    Restrict each element's attributes to the keep set (plus data-bounds), and
    truncate long values to strip script-in-attribute noise.
    """

    def __init__(self, keep_attrs=None, max_attr_len=MAX_ATTR_LEN):
        self.keep_attrs = set(keep_attrs) if keep_attrs is not None else set(KEEP_ATTRS)
        self.max_attr_len = max_attr_len

    def _clean(self, val):
        if isinstance(val, list):
            val = " ".join(val)
        val = " ".join(val.split())
        if len(val) > self.max_attr_len:
            val = val[: self.max_attr_len] + "..."
        return val

    def __call__(self, soup, parser):
        for tag in soup.find_all(True):
            kept = {}
            for key, val in (tag.attrs or {}).items():
                if key == "data-bounds" or key in self.keep_attrs:
                    kept[key] = self._clean(val)
            tag.attrs = kept
        return soup


class CleanEmpty(Rule):
    """
    Remove comments and any element left with no text, no meaningful attribute,
    and no bounds box after the earlier rules ran.
    """

    def __init__(self, keep_attrs=None):
        self.keep_attrs = set(keep_attrs) if keep_attrs is not None else set(KEEP_ATTRS)

    def __call__(self, soup, parser):
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()
        for tag in soup.find_all(True):
            has_text = bool(tag.get_text(strip=True))
            has_attr = any(a in (tag.attrs or {}) for a in self.keep_attrs)
            has_bounds = "data-bounds" in (tag.attrs or {})
            if not has_text and not has_attr and not has_bounds:
                tag.decompose()
        return soup


class StripInternalAttrs(Rule):
    """Remove scaffolding attributes (data-node-id) left by the builder."""

    def __init__(self, attrs=("data-node-id",)):
        self.attrs = attrs

    def __call__(self, soup, parser):
        for tag in soup.find_all(True):
            for a in self.attrs:
                if a in (tag.attrs or {}):
                    del tag.attrs[a]
        return soup
