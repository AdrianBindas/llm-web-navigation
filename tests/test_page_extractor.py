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
    # Element nodes AND laid-out text nodes (3, 5) carry their own bounds.
    layout = {i: (10 * i, 10 * i, 50 + i, 20 + i) for i in (1, 2, 3, 4, 5, 6, 7, 8)}
    soup, _ = filtered_soup(make_snapshot(spec, layout))
    tags = [t.name for t in soup.find_all(True)]
    assert "button" in tags
    assert "img" in tags
    # Text survives and is positioned (text carries its own bounds).
    assert "Click" in soup.get_text()
    assert "Hello" in soup.get_text()
    # No orphan text at the top level: every text run lives in a bounded element.
    for text in soup.find_all(string=True):
        if text.strip():
            assert text.parent.get("data-bounds") is not None
    # Empty decorative div (node 6) dropped.
    assert (60, 60, 56, 26) not in boxes_of(soup)


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
        DropButtons(), CleanEmpty(), KeepAttrs(),
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



# --- Text positioning ------------------------------------------------------


def test_text_node_wrapped_with_own_bounds(make_snapshot):
    # A laid-out text node is emitted as a span carrying its own bounds.
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0},
        {"name": "#text", "type": 3, "parent": 1, "value": "Hi"},
    ]
    # Text node (2) has its own tight box, distinct from the div (1).
    snap = make_snapshot(spec, {1: (0, 0, 100, 40), 2: (5, 12, 20, 16)})
    parser = SnapshotParser(snap)
    soup = HtmlBuilder(parser).to_soup()
    text_span = soup.find(string="Hi").parent
    assert text_span.get("data-bounds") == "5,12,20,16"


def test_orphan_text_without_bounds_dropped(make_snapshot):
    # Text with no layout box (not on screen) must not appear as loose text.
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0},
        {"name": "#text", "type": 3, "parent": 1, "value": "hover-only"},
    ]
    # Only the div has bounds; the text node has none.
    snap = make_snapshot(spec, {1: (0, 0, 100, 40)})
    parser = SnapshotParser(snap)
    soup = HtmlBuilder(parser).to_soup()
    assert "hover-only" not in soup.get_text()


def test_hidden_text_with_bounds_dropped(make_snapshot):
    # Text may have its own layout box yet be visibility:hidden (e.g. tooltip
    # labels). Such text is not on screen and must not be emitted.
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0},
        {"name": "#text", "type": 3, "parent": 1, "value": "tooltip",
         "styles": {"visibility": "hidden"}},
    ]
    snap = make_snapshot(spec, {1: (0, 0, 100, 40), 2: (5, 12, 40, 16)})
    parser = SnapshotParser(snap)
    soup = HtmlBuilder(parser).to_soup()
    assert "tooltip" not in soup.get_text()


# --- Collapse wrappers -----------------------------------------------------


def test_collapse_merges_plain_wrapper(make_snapshot):
    # div > span(text): both non-interactible -> collapse to the inner text span.
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0},
        {"name": "span", "type": 1, "parent": 1},
        {"name": "#text", "type": 3, "parent": 2, "value": "label"},
    ]
    snap = make_snapshot(spec, {1: (0, 0, 30, 20), 2: (2, 2, 26, 16), 3: (2, 2, 26, 16)})
    parser = SnapshotParser(snap)
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    # The outer div is gone; the text remains positioned.
    assert "label" in soup.get_text()
    assert soup.find_all("div") == []


def test_collapse_preserves_clickable_and_text(make_snapshot):
    # a(clickable) > span(text): must NOT collapse; keep both distinct.
    spec = [
        DOCUMENT,
        {"name": "a", "type": 1, "parent": 0, "attrs": [("href", "/x")]},
        {"name": "span", "type": 1, "parent": 1},
        {"name": "#text", "type": 3, "parent": 2, "value": "go"},
    ]
    snap = make_snapshot(spec, {1: (0, 0, 40, 20), 2: (2, 2, 36, 16), 3: (2, 2, 36, 16)})
    parser = SnapshotParser(snap)
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    a = soup.find("a")
    assert a is not None
    assert a.get("href") == "/x"
    # The text-carrying span stays nested inside the anchor.
    assert a.find(string="go") is not None


def test_collapse_never_removes_interactible_parent(make_snapshot):
    # a(clickable) > button(clickable) > text: both are interactible. The
    # anchor must NOT be removed and no interactible bounds may change, even
    # though it is a single-child wrapper.
    spec = [
        DOCUMENT,
        {"name": "a", "type": 1, "parent": 0, "attrs": [("href", "/x")]},
        {"name": "button", "type": 1, "parent": 1},
        {"name": "#text", "type": 3, "parent": 2, "value": "buy"},
    ]
    snap = make_snapshot(
        spec,
        {1: (0, 0, 50, 30), 2: (5, 5, 40, 20), 3: (7, 7, 30, 14)},
    )
    parser = SnapshotParser(snap)
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    a = soup.find("a")
    button = soup.find("button")
    # Both interactible elements survive.
    assert a is not None
    assert button is not None
    # Their bounding boxes are unchanged.
    assert a.get("data-bounds") == "0,0,50,30"
    assert button.get("data-bounds") == "5,5,40,20"
    # The button stays nested inside the anchor (structure preserved).
    assert a.find("button") is button


def test_collapse_keeps_interactible_child_bounds(make_snapshot):
    # div(plain wrapper) > button(clickable): the wrapper collapses, but the
    # interactible child keeps its own unchanged bounds.
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0},
        {"name": "button", "type": 1, "parent": 1},
        {"name": "#text", "type": 3, "parent": 2, "value": "ok"},
    ]
    snap = make_snapshot(
        spec,
        {1: (0, 0, 60, 40), 2: (10, 10, 40, 20), 3: (12, 12, 30, 14)},
    )
    parser = SnapshotParser(snap)
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    assert soup.find_all("div") == []          # plain wrapper collapsed
    button = soup.find("button")
    assert button is not None
    assert button.get("data-bounds") == "10,10,40,20"  # child bounds unchanged



# --- Interactible marking / compaction -------------------------------------


def test_mark_interactible_stamps_flag(make_snapshot):
    # A cursor:pointer div (interactible) gets data-interactible="true".
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0, "styles": {"cursor": "pointer"}},
        {"name": "#text", "type": 3, "parent": 1, "value": "x"},
    ]
    snap = make_snapshot(spec, {1: (0, 0, 40, 20), 2: (2, 2, 20, 14)})
    parser = SnapshotParser(snap)
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    marked = [t for t in soup.find_all(True) if t.get("data-interactible") == "true"]
    assert marked, "expected at least one element flagged interactible"


def test_compact_interactible_wrapper_moves_flag_to_child(make_snapshot):
    # Interactible wrapper (cursor:pointer div) around a plain span with text:
    # the wrapper is unwrapped and the flag moves to the span, which keeps its
    # own (smaller) bounds.
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0, "styles": {"cursor": "pointer"}},
        {"name": "span", "type": 1, "parent": 1},
        {"name": "#text", "type": 3, "parent": 2, "value": "buy"},
    ]
    snap = make_snapshot(
        spec,
        {1: (0, 0, 60, 40), 2: (10, 10, 30, 16), 3: (10, 10, 30, 16)},
    )
    parser = SnapshotParser(snap)
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    # The interactible div wrapper is gone.
    assert soup.find_all("div") == []
    span = soup.find("span")
    assert span is not None
    # Flag moved to the surviving child, which keeps its own tighter bounds.
    assert span.get("data-interactible") == "true"
    assert span.get("data-bounds") == "10,10,30,16"


def test_nested_interactibles_not_compacted(make_snapshot):
    # a(clickable) > button(clickable): two interactible elements may map to
    # different actions (hover vs click) -> both preserved, both flagged.
    spec = [
        DOCUMENT,
        {"name": "a", "type": 1, "parent": 0, "attrs": [("href", "/x")]},
        {"name": "button", "type": 1, "parent": 1},
        {"name": "#text", "type": 3, "parent": 2, "value": "go"},
    ]
    snap = make_snapshot(
        spec,
        {1: (0, 0, 50, 30), 2: (5, 5, 40, 20), 3: (7, 7, 30, 14)},
    )
    parser = SnapshotParser(snap)
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    a = soup.find("a")
    button = soup.find("button")
    assert a is not None and button is not None
    assert a.get("data-interactible") == "true"
    assert button.get("data-interactible") == "true"
    # Structure and bounds preserved.
    assert a.find("button") is button
    assert a.get("data-bounds") == "0,0,50,30"
    assert button.get("data-bounds") == "5,5,40,20"



def test_compact_nested_flag_collapses_nested_interactibles(make_snapshot):
    # With compact_nested=True, a(clickable) > span(cursor:pointer) collapses:
    # the outer wrapper is dropped, the interactible child survives with its
    # own bounds.
    from page_extractor import (
        CleanEmpty,
        CollapseWrappers,
        CompactInteractible,
        KeepAttrs,
        MarkInteractible,
        StripTags,
        UnwrapHidden,
        UnwrapUnkept,
    )

    spec = [
        DOCUMENT,
        {"name": "a", "type": 1, "parent": 0, "styles": {"cursor": "pointer"}},
        {"name": "span", "type": 1, "parent": 1, "styles": {"cursor": "pointer"}},
        {"name": "#text", "type": 3, "parent": 2, "value": "go"},
    ]
    snap = make_snapshot(
        spec,
        {1: (0, 0, 60, 30), 2: (5, 5, 40, 16), 3: (5, 5, 40, 16)},
    )
    parser = SnapshotParser(snap)
    rules = [
        StripTags(), UnwrapHidden(), UnwrapUnkept(), MarkInteractible(),
        CollapseWrappers(), CompactInteractible(compact_nested=True),
        CleanEmpty(), KeepAttrs(),
    ]
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, rules)
    # The anchor wrapper is gone; the interactible span survives.
    assert soup.find_all("a") == []
    span = soup.find("span")
    assert span is not None
    assert span.get("data-interactible") == "true"
    assert span.get("data-bounds") == "5,5,40,16"



def test_extract_boxes_with_flags_reports_interactibility(make_snapshot):
    # A button (interactible) and a plain text div: the flag distinguishes them
    # so annotate can color interactible boxes differently.
    spec = [
        DOCUMENT,
        {"name": "button", "type": 1, "parent": 0},
        {"name": "#text", "type": 3, "parent": 1, "value": "A"},
        {"name": "div", "type": 1, "parent": 0},
        {"name": "#text", "type": 3, "parent": 3, "value": "B"},
    ]
    snap = make_snapshot(
        spec,
        {1: (0, 0, 20, 10), 2: (1, 1, 18, 8), 3: (0, 20, 20, 10), 4: (1, 21, 18, 8)},
    )
    parser = SnapshotParser(snap)
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    pairs = OutputWriter().extract_boxes_with_flags(soup)
    flags = {box: inter for box, inter in pairs}
    # The button's box is flagged interactible; the plain text box is not.
    assert flags.get((0, 0, 20, 10)) is True
    assert any(not inter for _, inter in pairs)



def test_js_clickable_detected_via_is_clickable(make_snapshot):
    # A div with no interactible tag/role and cursor:auto, but flagged by CDP's
    # isClickable (a JS @click handler), must be detected as interactible.
    # Mirrors bilibili's login entry.
    spec = [
        DOCUMENT,
        {"name": "div", "type": 1, "parent": 0, "styles": {"cursor": "auto"}},
        {"name": "#text", "type": 3, "parent": 1, "value": "login"},
    ]
    snap = make_snapshot(spec, {1: (0, 0, 40, 20), 2: (5, 5, 30, 14)})
    # Inject CDP's isClickable rare-boolean flagging the div (node 1).
    snap["documents"][0]["nodes"]["isClickable"] = {"index": [1]}

    parser = SnapshotParser(snap)
    # Without the flag it would not be interactible (cursor:auto, plain div).
    assert parser.is_clickable(1) is True
    soup = apply_rules(HtmlBuilder(parser).to_soup(), parser, default_rules())
    marked = [t for t in soup.find_all(True) if t.get("data-interactible") == "true"]
    assert marked, "JS-clickable div should be marked interactible"
