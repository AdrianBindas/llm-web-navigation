"""Shared pytest fixtures and helpers for the page_extractor tests.

Builds minimal synthetic DOMSnapshots (matching the CDP
DOMSnapshot.captureSnapshot shape) so the parser, builder, and rules can be
exercised without a browser.
"""

import pytest

from page_extractor import HtmlBuilder, OutputWriter, SnapshotParser
from page_extractor.constants import COMPUTED_STYLE_KEYS
from page_extractor.page_extractor import apply_rules, default_rules


def _make_snapshot(nodes_spec, viewport_bounds):
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
            for k in COMPUTED_STYLE_KEYS
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


@pytest.fixture
def make_snapshot():
    """Factory fixture returning the synthetic-snapshot builder."""
    return _make_snapshot


@pytest.fixture
def filtered_soup(make_snapshot):
    """
    Factory fixture: given a snapshot (and optional rules) return
    (filtered_soup, parser) after running the builder and rule pipeline.
    """
    def _filtered(snap, rules=None):
        parser = SnapshotParser(snap)
        soup = HtmlBuilder(parser).to_soup()
        return apply_rules(soup, parser, rules or default_rules()), parser

    return _filtered


@pytest.fixture
def boxes_of():
    """Factory fixture returning a helper that extracts boxes from a soup."""
    return OutputWriter().extract_boxes



# --- Qwen integration test gating ------------------------------------------
# Tests marked ``@pytest.mark.qwen`` load the real Qwen model and are skipped
# unless explicitly enabled, either with the ``--run-qwen`` CLI flag or by
# setting ``run_qwen = true`` under ``[tool.pytest.ini_options]`` in
# pyproject.toml (exposed here as the ``run_qwen`` ini option).


def pytest_addoption(parser):
    parser.addoption(
        "--run-qwen",
        action="store_true",
        default=False,
        help="Run tests that load the real Qwen model.",
    )
    parser.addini(
        "run_qwen",
        help="Run tests that load the real Qwen model.",
        type="bool",
        default=False,
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "qwen: test that loads the real Qwen model (opt-in)."
    )


def _qwen_enabled(config):
    return bool(config.getoption("--run-qwen") or config.getini("run_qwen"))


def pytest_collection_modifyitems(config, items):
    if _qwen_enabled(config):
        return
    skip_qwen = pytest.mark.skip(
        reason="needs --run-qwen (or run_qwen=true in pyproject) to load Qwen."
    )
    for item in items:
        if "qwen" in item.keywords:
            item.add_marker(skip_qwen)
