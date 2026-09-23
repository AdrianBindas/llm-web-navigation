
from bs4 import BeautifulSoup

from .constants import (
    DOCUMENT_NODE,
    ELEMENT_NODE,
    TEXT_NODE,
)


class HtmlBuilder:
    """
    Serializes a parsed snapshot into a full HTML tree with no filtering. Every
    element node is emitted with a 'data-node-id' attribute (so rules can look
    the node back up in the parser) and, when visible, a 'data-bounds' attribute.
    Filtering happens afterwards by running rules over the produced soup.
    """

    def __init__(self, parser):
        self.parser = parser

    def build(self):
        """Return the full, unfiltered HTML string for the snapshot."""
        p = self.parser
        html = self._build(p.root)
        if not html.strip():
            html = "".join(
                self._build(i) for i, par in enumerate(p.parents) if par == -1
            )
        return html

    def to_soup(self):
        """Return a BeautifulSoup of the full, unfiltered tree."""
        return BeautifulSoup(self.build(), "html.parser")

    def _emit_attrs(self, node_id):
        p = self.parser
        parts = [f'data-node-id="{node_id}"']
        bounds = p.visible_map.get(node_id)
        if bounds is not None:
            x, y, w, h = bounds
            parts.append(f'data-bounds="{x:.0f},{y:.0f},{w:.0f},{h:.0f}"')
        for key, val in p.iter_attrs(node_id):
            safe = val.replace('"', "&quot;")
            parts.append(f'{key}="{safe}"')
        return " " + " ".join(parts)

    def _build(self, node_id):
        p = self.parser
        node_type = p.type_of(node_id)

        if node_type == TEXT_NODE:
            return p.text_of(node_id).strip()

        if node_type == DOCUMENT_NODE:
            return "".join(self._build(c) for c in p.children[node_id])

        if node_type == ELEMENT_NODE:
            name = p.tag_of(node_id)
            inner = "".join(self._build(c) for c in p.children[node_id])
            attrs = self._emit_attrs(node_id)
            return f"<{name}{attrs}>{inner}</{name}>"

        return ""

