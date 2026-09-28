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
            if nid is None:
                logger.warning(
                    "UnwrapHidden: <%s> has no data-node-id; cannot check "
                    "visibility, leaving it in place. Ensure attribute-"
                    "restricting rules run after UnwrapHidden.", tag.name,
                )
                continue
            if not parser.is_visible(nid):
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
        if parser.styles_of(node_id).get("cursor") == "pointer":
            return True
        # CDP-detected click handler (catches JS-driven clickables that have no
        # semantic tag, role, or cursor:pointer, e.g. Vue @click divs).
        return parser.is_clickable(node_id)

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
                logger.warning(
                    "UnwrapUnkept: <%s> has no data-node-id; cannot check "
                    "keep-worthiness, leaving it in place. Ensure attribute-"
                    "restricting rules run after UnwrapUnkept.", tag.name,
                )
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


class CollapseWrappers(Rule):
    """
    Collapse redundant single-child wrapper nesting. A parent element is merged
    into its only element child (the parent tag is dropped, the child kept) when
    the parent adds nothing distinct: it has no direct text of its own and no
    meaningful attributes beyond bounds/node-id.

    Interactible elements are never removed and their bounds never change: the
    parent (the element that would be unwrapped) is only collapsed when it is
    NOT interactible. A collapse therefore only ever discards a plain wrapper;
    the surviving child keeps its own tag and its own bounds.
    """

    def __init__(self, keep_attrs=None):
        self.keep_attrs = set(keep_attrs) if keep_attrs is not None else set(KEEP_ATTRS)
        # Attributes that do not count as "meaningful" for the parent.
        self._ignorable = {"data-bounds", "data-node-id"}
        self._interactibility = UnwrapUnkept()

    def _meaningful_attrs(self, tag):
        return {
            k for k in (tag.attrs or {})
            if k not in self._ignorable and k in self.keep_attrs
        }

    def _is_interactible(self, tag, parser):
        """
        Whether the tag is interactible. Requires the builder's data-node-id to
        be present; warns and treats the element as non-interactible if it is
        missing (e.g. attributes were restricted before this rule ran).
        """
        nid = node_id_of(tag)
        if nid is None:
            logger.warning(
                "CollapseWrappers: <%s> has no data-node-id; cannot check "
                "interactibility. Ensure attribute-restricting rules run after "
                "CollapseWrappers.", tag.name,
            )
            return False
        return self._interactibility.is_interactible(parser, nid)

    def _own_text(self, tag):
        """Text that is a direct (non-element) child of tag."""
        return "".join(
            str(c) for c in tag.contents if isinstance(c, str)
        ).strip()

    def __call__(self, soup, parser):
        changed = True
        # Iterate to a fixed point so chains of length > 2 fully collapse.
        while changed:
            changed = False
            for tag in soup.find_all(True):
                if tag.parent is None:
                    continue
                child_elements = [c for c in tag.contents if getattr(c, "name", None)]
                # Single element child, no direct text of the parent's own.
                if len(child_elements) != 1 or self._own_text(tag):
                    continue
                # Parent must add nothing meaningful beyond bounds/node-id.
                if self._meaningful_attrs(tag):
                    continue
                # Never remove an interactible element or alter its bounds: only
                # a non-interactible parent (the tag being dropped) may collapse.
                if self._is_interactible(tag, parser):
                    continue
                # Merge: keep the inner child (its own tag and bounds), drop the
                # plain wrapper.
                tag.unwrap()
                changed = True
                break
        return soup


class MarkInteractible(Rule):
    """
    Stamp data-interactible="true" on every element the interactibility
    definition considers clickable (tag/role/cursor). Makes interactibility an
    explicit, observable attribute so later rules and downstream consumers can
    act on it. Requires the builder's data-node-id to still be present.
    """

    def __init__(self):
        self._interactibility = UnwrapUnkept()

    def __call__(self, soup, parser):
        for tag in soup.find_all(True):
            nid = node_id_of(tag)
            if nid is None:
                logger.warning(
                    "MarkInteractible: <%s> has no data-node-id; cannot check "
                    "interactibility. Ensure attribute-restricting rules run "
                    "after MarkInteractible.", tag.name,
                )
                continue
            if self._interactibility.is_interactible(parser, nid):
                tag["data-interactible"] = "true"
        return soup


class CompactInteractible(Rule):
    """
    Compact an interactible single-child wrapper into its child: unwrap the
    interactible parent and move its data-interactible flag onto the surviving
    child, which keeps its own (tighter) bounds. Reduces element count while
    preserving that the region is interactible.

    Runs after MarkInteractible (needs data-interactible present). Only compacts
    when the parent adds nothing meaningful beyond bounds/node-id/interactible
    and has no direct text.

    compact_nested controls what happens when the single child is ITSELF
    interactible:
      - False (default): keep both. Two nested interactible elements may map to
        different actions (e.g. hover vs click), so both are preserved.
      - True: unwrap the parent anyway, keeping the (already interactible)
        child. Useful to collapse the deep interactible chains that CSS
        cursor:pointer inheritance produces, at the cost of merging the two
        actions into the child's element/bounds.
    """

    def __init__(self, keep_attrs=None, compact_nested=False):
        self.keep_attrs = set(keep_attrs) if keep_attrs is not None else set(KEEP_ATTRS)
        self.compact_nested = compact_nested
        self._ignorable = {"data-bounds", "data-node-id", "data-interactible"}

    def _meaningful_attrs(self, tag):
        return {
            k for k in (tag.attrs or {})
            if k not in self._ignorable and k in self.keep_attrs
        }

    def _own_text(self, tag):
        return "".join(
            str(c) for c in tag.contents if isinstance(c, str)
        ).strip()

    def __call__(self, soup, parser):
        changed = True
        while changed:
            changed = False
            for tag in soup.find_all(True):
                if tag.parent is None:
                    continue
                # Only interactible wrappers are handled here.
                if tag.get("data-interactible") != "true":
                    continue
                child_elements = [c for c in tag.contents if getattr(c, "name", None)]
                if len(child_elements) != 1 or self._own_text(tag):
                    continue
                if self._meaningful_attrs(tag):
                    continue
                child = child_elements[0]
                # When the child is itself interactible, keep both unless nested
                # compaction is explicitly enabled (distinct actions such as
                # hover vs click may otherwise be lost).
                if child.get("data-interactible") == "true":
                    if not self.compact_nested:
                        continue
                    # Child already carries the flag; just drop the wrapper.
                    tag.unwrap()
                    changed = True
                    break
                # Move the interactible flag down to the surviving child, which
                # keeps its own (smaller) bounds; drop the wrapper.
                child["data-interactible"] = "true"
                tag.unwrap()
                changed = True
                break
        return soup
