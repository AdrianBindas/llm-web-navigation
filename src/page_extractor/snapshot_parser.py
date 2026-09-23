import logging

from .constants import (
    COMPUTED_STYLE_KEYS,
    VIEWPORT,
)

logger = logging.getLogger(__name__)


class SnapshotParser:
    """
    Wraps a single CDP DOMSnapshot.captureSnapshot result and precomputes the
    structures needed to reason about nodes: parent/child adjacency, the layout
    bounds map, and the computed-styles map.

    The parser is purely structural: it exposes node names, attributes, text,
    bounds, styles, and a visibility predicate.
    """

    def __init__(self, snapshot, viewport=None, computed_style_keys=None):
        self.snapshot = snapshot
        self.viewport = viewport or dict(VIEWPORT)
        self.computed_style_keys = computed_style_keys or list(COMPUTED_STYLE_KEYS)

        doc = snapshot["documents"][0]
        nodes = doc["nodes"]
        self.strings = snapshot["strings"]
        self.node_names = nodes["nodeName"]
        self.node_types = nodes["nodeType"]
        self.node_values = nodes["nodeValue"]
        self.parents = nodes["parentIndex"]
        self.attributes = nodes.get("attributes", [])

        self.total_nodes = len(self.node_names)
        self.children, self.root = self._build_adjacency()
        self.visible_map = self._build_visible_map()
        self.styles_map = self._build_styles_map()

    # -- construction helpers --

    def _build_adjacency(self):
        children = [[] for _ in range(self.total_nodes)]
        root = None
        for i, parent in enumerate(self.parents):
            if parent == -1:
                root = i
            else:
                children[parent].append(i)
        if root is None:
            root = 0
        return children, root

    def _build_visible_map(self):
        """Map node_id -> (x, y, w, h) for nodes with positive-size layout bounds."""
        doc = self.snapshot["documents"][0]
        layout = doc.get("layout", {})
        node_indices = layout.get("nodeIndex", [])
        bounds = layout.get("bounds", [])
        if len(bounds) != len(node_indices):
            logger.warning("Node bounding might not have been determined correctly.")
        visible = {}
        for i, node_id in enumerate(node_indices):
            x, y, w, h = bounds[i]
            if w > 0 and h > 0:
                visible[node_id] = (x, y, w, h)
        return visible

    def _build_styles_map(self):
        """
        Map node_id -> {style_key: value} from layout.styles (parallel to
        layout.nodeIndex). Reads the layout array directly; does not depend on
        the optional nodes.computedStyles array.
        """
        doc = self.snapshot["documents"][0]
        layout = doc.get("layout", {})
        node_indices = layout.get("nodeIndex", [])
        layout_styles = layout.get("styles", [])
        if not layout_styles:
            return {}
        keys = self.computed_style_keys
        key_count = len(keys)
        result = {}
        for i, node_id in enumerate(node_indices):
            if i >= len(layout_styles):
                break
            style_vals = layout_styles[i]
            if len(style_vals) < key_count:
                continue
            result[node_id] = {
                keys[j]: (self.strings[v] if v != -1 else "")
                for j, v in enumerate(style_vals[:key_count])
            }
        return result

    # -- string / attribute helpers --

    def get_string(self, idx):
        return "" if idx == -1 else self.strings[idx]

    def tag_of(self, node_id):
        return self.get_string(self.node_names[node_id]).lower()

    def text_of(self, node_id):
        return self.get_string(self.node_values[node_id])

    def type_of(self, node_id):
        return self.node_types[node_id]

    def styles_of(self, node_id):
        """Return the computed-style dict for a node, or {} if none."""
        return self.styles_map.get(node_id) or {}

    def iter_attrs(self, node_id):
        """Yield (key, value) pairs for a node's attributes."""
        attr_list = self.attributes[node_id] if self.attributes else []
        for i in range(0, len(attr_list) - 1, 2):
            yield self.strings[attr_list[i]], self.strings[attr_list[i + 1]]

    def get_attr(self, node_id, wanted):
        for key, val in self.iter_attrs(node_id):
            if key == wanted:
                return val
        return ""

    # -- visibility predicates (structural, not filtering) --

    def is_out_of_viewport(self, node_id):
        bounds = self.visible_map.get(node_id)
        if bounds is None:
            return True
        x, y, w, h = bounds
        vp = self.viewport
        return x + w <= 0 or y + h <= 0 or x >= vp["width"] or y >= vp["height"]

    def is_style_hidden(self, node_id):
        styles = self.styles_map.get(node_id)
        if not styles:
            return False
        if styles.get("display") == "none":
            return True
        if styles.get("visibility") in ("hidden", "collapse"):
            return True
        try:
            if float(styles.get("opacity", "1")) == 0.0:
                return True
        except (ValueError, TypeError):
            pass
        return False

    def is_attr_hidden(self, node_id):
        for key, val in self.iter_attrs(node_id):
            if key == "aria-hidden" and val == "true":
                return True
            if key == "hidden":
                return True
        return False

    def is_visible(self, node_id):
        """
        True only when the node passes every visibility check: has positive-size
        bounds, is within the viewport, is not CSS-hidden, and carries no
        aria-hidden/hidden attribute. Ancestor-level hiding is implicit: children
        of display:none parents are absent from the layout nodeIndex.
        """
        if node_id not in self.visible_map:
            return False
        if self.is_out_of_viewport(node_id):
            return False
        if self.is_style_hidden(node_id):
            return False
        return not self.is_attr_hidden(node_id)
