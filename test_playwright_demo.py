"""
Deterministic tests for playwright_demo filtering logic.

Builds a small synthetic DOMSnapshot (matching the CDP DOMSnapshot.captureSnapshot
shape) so the predicates and tree pruning can be exercised without a browser.
"""

from bs4 import BeautifulSoup

import playwright_demo as pd


def make_snapshot(nodes_spec, viewport_bounds):
    """
    Build a minimal snapshot from a compact spec.

    nodes_spec: list of dicts with keys:
        name (tag or '#text'), type (1/3/9), parent (index or -1),
        value (text, optional), attrs (list of (k, v), optional),
        styles (dict of style_key->value, optional)
    viewport_bounds: dict node_index -> (x, y, w, h) for nodes that have layout
    """
    strings = []

    def intern(s):
        if s in strings:
            return strings.index(s)
        strings.append(s)
        return len(strings) - 1

    node_name, node_type, node_value, parent_index, attributes = [], [], [], [], []
    for spec in nodes_spec:
        node_name.append(intern(spec["name"]))
        node_type.append(spec["type"])
        node_value.append(intern(spec["value"]) if "value" in spec else -1)
        parent_index.append(spec["parent"])
        attr_flat = []
        for k, v in spec.get("attrs", []):
            attr_flat.extend([intern(k), intern(v)])
        attributes.append(attr_flat)

    node_index, bounds, style_rows = [], [], []
    for idx, (x, y, w, h) in viewport_bounds.items():
        node_index.append(idx)
        bounds.append([x, y, w, h])
        styles = nodes_spec[idx].get("styles", {})
        style_rows.append([
            intern(styles.get(k, "")) if k in styles else -1
            for k in pd.COMPUTED_STYLE_KEYS
        ])

    return {
        "strings": strings,
        "documents": [{
            "nodes": {
                "nodeName": node_name,
                "nodeType": node_type,
                "nodeValue": node_value,
                "parentIndex": parent_index,
                "attributes": attributes,
            },
            "layout": {
                "nodeIndex": node_index,
                "bounds": bounds,
                "styles": style_rows,
            },
        }],
    }


def bounds_full():
    return (10, 10, 100, 30)


def test_computed_styles_map_and_style_hidden():
    spec = [
        {"name": "#document", "type": 9, "parent": -1},
        {"name": "div", "type": 1, "parent": 0, "styles": {"display": "none"}},
        {"name": "div", "type": 1, "parent": 0, "styles": {"cursor": "pointer"}},
    ]
    snap = make_snapshot(spec, {1: bounds_full(), 2: bounds_full()})
    m = pd.build_computed_styles_map(snap)
    assert m[1]["display"] == "none"
    assert m[2]["cursor"] == "pointer"
    assert pd.is_style_hidden(1, m) is True
    assert pd.is_style_hidden(2, m) is False


def test_is_interactible():
    spec = [
        {"name": "#document", "type": 9, "parent": -1},
        {"name": "button", "type": 1, "parent": 0},
        {"name": "div", "type": 1, "parent": 0, "attrs": [("role", "button")]},
        {"name": "div", "type": 1, "parent": 0, "styles": {"cursor": "pointer"}},
        {"name": "div", "type": 1, "parent": 0},
    ]
    snap = make_snapshot(spec, {i: bounds_full() for i in (1, 2, 3, 4)})
    m = pd.build_computed_styles_map(snap)
    strings = snap["strings"]
    attrs = snap["documents"][0]["nodes"]["attributes"]

    assert pd.is_interactible(1, "button", m, attrs, strings) is True   # tag
    assert pd.is_interactible(2, "div", m, attrs, strings) is True      # role
    assert pd.is_interactible(3, "div", m, attrs, strings) is True      # cursor
    assert pd.is_interactible(4, "div", m, attrs, strings) is False     # plain


def test_direct_content_and_pruning():
    # Tree:
    #  0 #document
    #   1 div (wrapper, no direct content, not interactible) -> unwrapped
    #     2 button                                            -> kept
    #       3 #text "Click"
    #     4 div (wrapper around text)                         -> kept (direct text)
    #       5 #text "Hello"
    #     6 div (empty decorative)                            -> dropped
    #     7 div (contains img)                                -> kept (direct media)
    #       8 img
    spec = [
        {"name": "#document", "type": 9, "parent": -1},
        {"name": "div", "type": 1, "parent": 0},
        {"name": "button", "type": 1, "parent": 1},
        {"name": "#text", "type": 3, "parent": 2, "value": "Click"},
        {"name": "div", "type": 1, "parent": 1},
        {"name": "#text", "type": 3, "parent": 4, "value": "Hello"},
        {"name": "div", "type": 1, "parent": 1},
        {"name": "div", "type": 1, "parent": 1},
        {"name": "img", "type": 1, "parent": 7, "attrs": [("src", "a.png")]},
    ]
    layout = {i: (10 * i, 10 * i, 50 + i, 20 + i) for i in (1, 2, 4, 6, 7, 8)}
    snap = make_snapshot(spec, layout)

    html = pd.snapshot_to_html_with_layout(snap)
    soup = pd.clean_soup(BeautifulSoup(html, "html.parser"))

    tags = [t.name for t in soup.find_all(True)]
    # wrapper div (node 1) and empty div (node 6) are gone
    assert "button" in tags
    assert "img" in tags
    # exactly the qualifying elements carry bounds
    boxes = pd.extract_bounds(soup)
    # button, text-div, img-div, img = 4 boxes; wrapper + empty div excluded
    assert len(boxes) == 4, f"expected 4 boxes, got {len(boxes)}: {tags}"


def test_background_image_counts_as_content():
    # An empty div with a CSS background-image should be kept (icon case).
    spec = [
        {"name": "#document", "type": 9, "parent": -1},
        {"name": "div", "type": 1, "parent": 0,
         "styles": {"background-image": "url(icon.png)"}},
        {"name": "div", "type": 1, "parent": 0,
         "styles": {"background-image": "none"}},
    ]
    snap = make_snapshot(spec, {1: (10, 10, 40, 40), 2: (60, 10, 40, 40)})
    html = pd.snapshot_to_html_with_layout(snap)
    soup = pd.clean_soup(BeautifulSoup(html, "html.parser"))
    boxes = pd.extract_bounds(soup)
    # node 1 (background-image) kept; node 2 (none) dropped
    assert (10, 10, 40, 40) in boxes
    assert (60, 10, 40, 40) not in boxes


def test_attribute_value_truncated():
    js = ";(function(){ var x = 1; " + "a" * 400 + " })()"
    spec = [
        {"name": "#document", "type": 9, "parent": -1},
        {"name": "input", "type": 1, "parent": 0, "attrs": [("value", js)]},
    ]
    snap = make_snapshot(spec, {1: (10, 10, 100, 20)})
    html = pd.snapshot_to_html_with_layout(snap)
    # value present but clamped to MAX_ATTR_LEN + ellipsis, no newlines
    assert "value=" in html
    assert len(js) > pd.MAX_ATTR_LEN
    assert "a" * (pd.MAX_ATTR_LEN + 1) not in html
    assert "..." in html


def test_styles_map_built_without_computed_styles_key():
    # Regression: the map must come from layout.styles even when the snapshot
    # has no nodes.computedStyles array. A cursor:pointer div must be kept.
    spec = [
        {"name": "#document", "type": 9, "parent": -1},
        {"name": "div", "type": 1, "parent": 0, "styles": {"cursor": "pointer"}},
    ]
    snap = make_snapshot(spec, {1: (10, 10, 40, 40)})
    assert "computedStyles" not in snap["documents"][0]["nodes"]
    m = pd.build_computed_styles_map(snap)
    assert m, "styles map should not be empty"
    assert m[1]["cursor"] == "pointer"

    html = pd.snapshot_to_html_with_layout(snap)
    soup = pd.clean_soup(BeautifulSoup(html, "html.parser"))
    # cursor:pointer div is interactible -> kept even with no text/media
    assert (10, 10, 40, 40) in pd.extract_bounds(soup)


def test_extended_keep_tags_and_roles():
    # form + fieldset (interactive tags), canvas (media), search role are kept
    # even without direct text.
    spec = [
        {"name": "#document", "type": 9, "parent": -1},
        {"name": "form", "type": 1, "parent": 0, "attrs": [("action", "/go")]},
        {"name": "canvas", "type": 1, "parent": 0},
        {"name": "div", "type": 1, "parent": 0, "attrs": [("role", "search")]},
        {"name": "div", "type": 1, "parent": 0},  # plain wrapper -> dropped
    ]
    layout = {1: (0, 0, 50, 10), 2: (0, 20, 50, 10),
              3: (0, 40, 50, 10), 4: (0, 60, 50, 10)}
    snap = make_snapshot(spec, layout)
    html = pd.snapshot_to_html_with_layout(snap)
    soup = pd.clean_soup(BeautifulSoup(html, "html.parser"))
    boxes = pd.extract_bounds(soup)

    assert (0, 0, 50, 10) in boxes    # form
    assert (0, 20, 50, 10) in boxes   # canvas
    assert (0, 40, 50, 10) in boxes   # role=search
    assert (0, 60, 50, 10) not in boxes  # plain empty div dropped


if __name__ == "__main__":
    test_computed_styles_map_and_style_hidden()
    test_is_interactible()
    test_direct_content_and_pruning()
    test_background_image_counts_as_content()
    test_attribute_value_truncated()
    test_styles_map_built_without_computed_styles_key()
    test_extended_keep_tags_and_roles()
    print("All tests passed.")
