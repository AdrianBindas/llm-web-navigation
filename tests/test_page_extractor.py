"""
Deterministic tests for the page_extractor pipeline.

Uses synthetic DOMSnapshots (see conftest.py) so the parser, builder, and rules
can be exercised without a browser.
"""

import pytest

from page_extractor import (
    CleanEmpty,
    HtmlBuilder,
    KeepAttrs,
    OutputConfig,
    OutputWriter,
    Rule,
    SnapshotParser,
    StripInternalAttrs,
    StripTags,
    UnwrapHidden,
    UnwrapUnkept,
)
from page_extractor.constants import MAX_ATTR_LEN
from page_extractor.page_extractor import apply_rules, default_rules

DOCUMENT = {"name": "#document", "type": 9, "parent": -1}


# --- Parser ----------------------------------------------------------------


def test_styles_map_built_without_computed_styles_key(make_snapshot):
    # Regression: the styles map must come from layout.styles even when the
    # snapshot has no nodes.computedStyles array.
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0, "styles": {"display": "none"}},
        {"name": "div", "type": 1, "parent": 0, "styles": {"cursor": "pointer"}},
    ]
    snap = make_snapshot(spec, {1: (10, 10, 100, 30), 2: (10, 50, 100, 30)})
    assert "computedStyles" not in snap["documents"][0]["nodes"]
    parser = SnapshotParser(snap)
    assert parser.styles_map, "styles map should not be empty"
    assert parser.styles_map[1]["display"] == "none"
    assert parser.styles_map[2]["cursor"] == "pointer"
    assert parser.is_style_hidden(1) is True
    assert parser.is_style_hidden(2) is False
    assert parser.is_visible(1) is False   # display:none
    assert parser.is_visible(2) is True


def test_parser_is_structural_only():
    # Filtering predicates must NOT live on the parser.
    assert not hasattr(SnapshotParser, "is_interactible")
    assert not hasattr(SnapshotParser, "has_direct_content")


# --- UnwrapUnkept (owns interactible / content) ----------------------------


@pytest.mark.parametrize(
    "node_id, predicate, expected",
    [
        (1, "is_interactible", True),    # button tag
        (2, "is_interactible", True),    # role=button
        (3, "is_interactible", True),    # cursor:pointer
        (4, "has_direct_content", True),  # img
        (5, "is_interactible", False),   # plain div
        (5, "has_direct_content", False),
    ],
)
def test_unwrap_unkept_predicates(make_snapshot, node_id, predicate, expected):
    rule = UnwrapUnkept()
    spec = [
        DOCUMENT,
        {"name": "button", "type": 1, "parent": 0},
        {"name": "div", "type": 1, "parent": 0, "attrs": [("role", "button")]},
        {"name": "div", "type": 1, "parent": 0, "styles": {"cursor": "pointer"}},
        {"name": "img", "type": 1, "parent": 0, "attrs": [("src", "a.png")]},
        {"name": "div", "type": 1, "parent": 0},  # plain -> not kept
    ]
    snap = make_snapshot(spec, {i: (0, 10 * i, 40, 10) for i in (1, 2, 3, 4, 5)})
    parser = SnapshotParser(snap)
    assert getattr(rule, predicate)(parser, node_id) is expected


# --- Full pipeline ---------------------------------------------------------


def test_pipeline_pruning(make_snapshot, filtered_soup, boxes_of):
    # wrapper div -> unwrapped; button (text) kept; text-div kept; empty div
    # dropped; div with direct img child kept.
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0},        # 1 wrapper
        {"name": "button", "type": 1, "parent": 1},     # 2
        {"name": "#text", "type": 3, "parent": 2, "value": "Click"},  # 3
        {"name": "div", "type": 1, "parent": 1},        # 4 text wrapper
        {"name": "#text", "type": 3, "parent": 4, "value": "Hello"},  # 5
        {"name": "div", "type": 1, "parent": 1},        # 6 empty decorative
        {"name": "div", "type": 1, "parent": 1},        # 7 img wrapper
        {"name": "img", "type": 1, "parent": 7, "attrs": [("src", "a.png")]},  # 8
    ]
    layout = {i: (10 * i, 10 * i, 50 + i, 20 + i) for i in (1, 2, 4, 6, 7, 8)}
    soup, _ = filtered_soup(make_snapshot(spec, layout))
    tags = [t.name for t in soup.find_all(True)]
    assert "button" in tags
    assert "img" in tags
    assert len(boxes_of(soup)) == 4, f"expected 4 boxes: {tags}"


def test_background_image_counts_as_content(make_snapshot, filtered_soup, boxes_of):
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0, "styles": {"background-image": "url(icon.png)"}},
        {"name": "div", "type": 1, "parent": 0, "styles": {"background-image": "none"}},
    ]
    soup, _ = filtered_soup(make_snapshot(spec, {1: (10, 10, 40, 40), 2: (60, 10, 40, 40)}))
    boxes = boxes_of(soup)
    assert (10, 10, 40, 40) in boxes
    assert (60, 10, 40, 40) not in boxes


def test_attribute_value_truncated(make_snapshot, filtered_soup):
    js = ";(function(){ var x = 1; " + "a" * 400 + " })()"
    spec = [
        DOCUMENT,
        {"name": "input", "type": 1, "parent": 0, "attrs": [("value", js)]},
    ]
    soup, _ = filtered_soup(make_snapshot(spec, {1: (10, 10, 100, 20)}))
    html = str(soup)
    assert "value=" in html
    assert len(js) > MAX_ATTR_LEN
    assert "a" * (MAX_ATTR_LEN + 1) not in html
    assert "..." in html


@pytest.mark.parametrize(
    "box, kept",
    [
        ((0, 0, 50, 10), True),    # form
        ((0, 20, 50, 10), True),   # canvas
        ((0, 40, 50, 10), True),   # role=search
        ((0, 60, 50, 10), False),  # plain div
    ],
)
def test_extended_keep_tags_and_roles(make_snapshot, filtered_soup, boxes_of, box, kept):
    spec = [
        DOCUMENT,
        {"name": "form", "type": 1, "parent": 0, "attrs": [("action", "/go")]},
        {"name": "canvas", "type": 1, "parent": 0},
        {"name": "div", "type": 1, "parent": 0, "attrs": [("role", "search")]},
        {"name": "div", "type": 1, "parent": 0},  # plain -> dropped
    ]
    layout = {1: (0, 0, 50, 10), 2: (0, 20, 50, 10),
              3: (0, 40, 50, 10), 4: (0, 60, 50, 10)}
    soup, _ = filtered_soup(make_snapshot(spec, layout))
    boxes = boxes_of(soup)
    assert (box in boxes) is kept


def test_no_internal_scaffolding_leaks(make_snapshot, filtered_soup):
    spec = [
        DOCUMENT,
        {"name": "button", "type": 1, "parent": 0},
        {"name": "#text", "type": 3, "parent": 1, "value": "Go"},
    ]
    soup, _ = filtered_soup(make_snapshot(spec, {1: (0, 0, 40, 10)}))
    assert "data-node-id" not in str(soup)


# --- Custom rule injection -------------------------------------------------


def test_custom_rule_injection(make_snapshot, filtered_soup):
    class DropButtons(Rule):
        def __call__(self, soup, parser):
            for t in soup.find_all("button"):
                t.decompose()
            return soup

    spec = [
        DOCUMENT,
        {"name": "button", "type": 1, "parent": 0},
        {"name": "#text", "type": 3, "parent": 1, "value": "Go"},
    ]
    snap = make_snapshot(spec, {1: (0, 0, 40, 10)})
    rules = [
        StripTags(), UnwrapHidden(), UnwrapUnkept(),
        DropButtons(), KeepAttrs(), CleanEmpty(), StripInternalAttrs(),
    ]
    soup, _ = filtered_soup(snap, rules)
    assert "button" not in [t.name for t in soup.find_all(True)]


def test_output_writer_unique_boxes(make_snapshot):
    writer = OutputWriter(OutputConfig(unique_boxes=True))
    spec = [
        DOCUMENT,
        {"name": "button", "type": 1, "parent": 0},
        {"name": "#text", "type": 3, "parent": 1, "value": "A"},
        {"name": "button", "type": 1, "parent": 0},
        {"name": "#text", "type": 3, "parent": 3, "value": "B"},
    ]
    # identical bounds on both buttons -> unique collapses to 1
    snap = make_snapshot(spec, {1: (5, 5, 10, 10), 3: (5, 5, 10, 10)})
    parser = SnapshotParser(snap)
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    assert len(writer.extract_boxes(soup)) == 1
