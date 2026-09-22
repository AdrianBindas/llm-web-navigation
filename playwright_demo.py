import io
import logging

from bs4 import BeautifulSoup, Comment
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

logger = logging.getLogger("__name__")

# Tags that should be stripped
STRIP_TAGS = {
    "script", "style", "link", "meta", "noscript", "head",
    "svg", "path", "symbol", "defs", "use",
    "iframe", "object", "embed", "applet",
}

# Attributes that keep meaningful information
KEEP_ATTRS = {
    "href", "src", "alt", "title", "aria-label", "role",
    "type", "name", "placeholder", "value", "action",
    "data-visible", "data-bounds",
}

VIEWPORT = {"width": 1280, "height": 800}

# Computed style indices within the snapshot's computedStyles array.
# Positions correspond to the order in COMPUTED_STYLE_KEYS below.
COMPUTED_STYLE_KEYS = ["display", "visibility", "opacity"]


def is_out_of_viewport(bounds, viewport=VIEWPORT):
    """Return True if the element is entirely outside the viewport."""
    x, y, w, h = bounds
    return (
        x + w <= 0
        or y + h <= 0
        or x >= viewport["width"]
        or y >= viewport["height"]
    )


def is_style_hidden(node_id, computed_styles_map):
    """
    Return True if the node's computed styles mark it as invisible.
    Checks display:none, visibility:hidden/collapse, opacity:0.
    """
    styles = computed_styles_map.get(node_id)
    if styles is None:
        return False
    display, visibility, opacity = styles
    if display == "none":
        return True
    if visibility in ("hidden", "collapse"):
        return True
    try:
        if float(opacity) == 0.0:
            return True
    except (ValueError, TypeError):
        pass
    return False


def is_attr_hidden(node_id, attributes, strings):
    """
    Return True if the node carries aria-hidden="true" or the HTML hidden attribute.
    """
    attr_list = attributes[node_id] if attributes else []
    for i in range(0, len(attr_list) - 1, 2):
        key = strings[attr_list[i]]
        val = strings[attr_list[i + 1]]
        if key == "aria-hidden" and val == "true":
            return True
        if key == "hidden":
            return True
    return False


def build_computed_styles_map(snapshot):
    """
    Build a dict mapping node_id → (display, visibility, opacity) strings
    from the CDP DOMSnapshot computedStyles data.
    Returns an empty dict if the snapshot doesn't include style data.
    """
    doc = snapshot["documents"][0]
    nodes = doc["nodes"]
    strings = snapshot["strings"]

    style_index = nodes.get("computedStyles")   # per-node list of style-value pairs
    layout = doc.get("layout", {})
    layout_node_indices = layout.get("nodeIndex", [])
    layout_styles = layout.get("styles", [])    # parallel array to nodeIndex

    if not style_index or not layout_styles:
        return {}

    # Build a fast lookup: node_id → style value array index
    node_to_layout = {node_id: i for i, node_id in enumerate(layout_node_indices)}

    result = {}
    # COMPUTED_STYLE_KEYS order must match the order passed to captureSnapshot
    key_count = len(COMPUTED_STYLE_KEYS)

    for node_id, layout_idx in node_to_layout.items():
        style_vals = layout_styles[layout_idx]  # list of value-string indices
        if len(style_vals) < key_count:
            continue
        resolved = tuple(strings[v] if v != -1 else "" for v in style_vals[:key_count])
        result[node_id] = resolved  # (display, visibility, opacity)

    return result


def is_visible(node_id, bounds_map, computed_styles_map, attributes, strings):
    """
    Combine all visibility signals into a single predicate.
    A node is truly visible only when it passes every check:
      1. Has positive-size bounds in the layout snapshot.
      2. Is not positioned entirely outside the viewport.
      3. Has no CSS property that hides it (display/visibility/opacity).
      4. Carries no aria-hidden or hidden attribute.
    Ancestor-level hiding is handled implicitly by the CDP layout snapshot:
    children of display:none parents are absent from the layout nodeIndex.
    """
    if node_id not in bounds_map:
        return False
    if is_out_of_viewport(bounds_map[node_id]):
        return False
    if is_style_hidden(node_id, computed_styles_map):
        return False
    return not is_attr_hidden(node_id, attributes, strings)


def get_visible_with_bounds(snapshot):
    """Extract nodes with positive width and height."""
    doc = snapshot["documents"][0]
    layout = doc.get("layout", {})
    node_indices = layout.get("nodeIndex", [])
    bounds = layout.get("bounds", [])
 
    visible = {}
    if len(bounds) != len(node_indices):
        logger.warning("Node bounding might not have been determined correctly.")
    for i, node_id in enumerate(node_indices):
        x, y, w, h = bounds[i]
        # TODO: Filter out negative x,y
        if w > 0 and h > 0:
            visible[node_id] = (x, y, w, h)
 
    return visible
 
 
def snapshot_to_html_with_layout(snapshot):
    doc = snapshot["documents"][0]
    nodes = doc["nodes"]
    strings = snapshot["strings"]
 
    node_names = nodes["nodeName"]
    node_types = nodes["nodeType"]
    node_values = nodes["nodeValue"]
    parents = nodes["parentIndex"]
    attributes = nodes.get("attributes", [])
 
    total_nodes = len(node_names)
    children = [[] for _ in range(total_nodes)]
    root = None
 
    for i, parent in enumerate(parents):
        if parent == -1:
            logger.info("Assigning root to id -1")
            root = i
        else:
            children[parent].append(i)
 
    if root is None:
        logger.info("Assigning root to id 0")
        root = 0

    visible_map = get_visible_with_bounds(snapshot)
    computed_styles_map = build_computed_styles_map(snapshot)

    # TODO: Traverse layout further for text.
  
    def get_string(idx):
        return "" if idx == -1 else strings[idx]
 
    def get_attrs(node_id):
        attr_list = attributes[node_id] if attributes else []
        parts = []
 
        for i in range(0, len(attr_list) - 1, 2):
            key = strings[attr_list[i]]
            val = strings[attr_list[i + 1]]
            if key in KEEP_ATTRS:
                parts.append(f'{key}="{val}"')
 
        if is_visible(node_id, visible_map, computed_styles_map, attributes, strings):
            x, y, w, h = visible_map[node_id]
            parts.append(f'data-bounds="{x:.0f},{y:.0f},{w:.0f},{h:.0f}"')
        else:
            parts.append('data-visible="false"')
 
        return (" " + " ".join(parts)) if parts else ""
 
    def build(node_id):
        name_idx = node_names[node_id]
        node_type = node_types[node_id]
        value = get_string(node_values[node_id])

        # TODO: Include ATTRIBUTE_NODE for backward compatibility
 
        # TEXT_NODE — keep non-empty text
        if node_type == 3:
            text = value.strip()
            return text if text else ""
  
        # DOCUMENT_NODE
        if node_type == 9:
            return "".join(build(child) for child in children[node_id])
 
        # ELEMENT_NODE
        if node_type == 1:
            name = get_string(name_idx).lower()
 
            # Drop non-content tags entirely
            if name in STRIP_TAGS:
                return ""
 
            is_visible_ = is_visible(node_id, visible_map, computed_styles_map, attributes, strings)
            inner = "".join(build(child) for child in children[node_id])
            
            if not is_visible_:
                return inner if inner.strip() else ""
 
            attrs = get_attrs(node_id)
            if not inner.strip() and not attrs.strip():
                return ""
            return f"<{name}{attrs}>{inner}</{name}>"
 
        return ""
 
    html = build(root)
    if not html.strip():
        html = "".join(build(i) for i, p in enumerate(parents) if p == -1)
 
    return html
 
 
def clean_soup(soup):
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
 
    for tag in soup.find_all(True):
        has_text = bool(tag.get_text(strip=True))
        has_attr = any(a in (tag.attrs or {}) for a in KEEP_ATTRS)
        if not has_text and not has_attr:
            tag.decompose()
 
    return soup
 
 
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
 
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport=VIEWPORT,
            locale="en-US",
            timezone_id="Europe/Bratislava",
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
 
        page = context.new_page()
 
        Stealth().apply_stealth_sync(page)
 
        page.goto("https://tiktok.com/", wait_until="networkidle", timeout=60000)
  
        screenshot_bytes = page.screenshot(full_page=False)
 
        client = page.context.new_cdp_session(page)
        snapshot = client.send("DOMSnapshot.captureSnapshot", {
            "computedStyles": COMPUTED_STYLE_KEYS,
        })
 
        html = snapshot_to_html_with_layout(snapshot)
        soup = BeautifulSoup(html, "html.parser")
        soup = clean_soup(soup)

        print(soup.prettify())
 
        boxes = extract_bounds(soup)
        print(f"Found {len(boxes)} bounding boxes.")
 
        annotated = annotate_screenshot(screenshot_bytes, boxes)
 
        out_path = "images/annotated_screenshot.png"
        annotated.save(out_path)
 
        browser.close()
 

def extract_bounds(soup, unique=True):
    """
    Walk the parsed HTML and collect every data-bounds value.
    Returns a list of (x, y, w, h) int tuples.
    """
    boxes = []
    for tag in soup.find_all(True):
        bounds_str = tag.get("data-bounds")
        if bounds_str:
            try:
                x, y, w, h = (int(v) for v in bounds_str.split(","))
                boxes.append((x, y, w, h))
            except ValueError:
                pass
    
    if unique:
        uniques = []
        for i, box in enumerate(boxes):
            if box not in boxes[i+1:]:
                uniques.append(box)
        return uniques

    return boxes


def annotate_screenshot(screenshot_bytes, boxes, color=(0, 200, 80)):
    """
    Draw semi-transparent filled rectangles + outlines for every bounding box.
 
    Args:
        screenshot_bytes: raw PNG bytes from Playwright
        boxes:            list of (x, y, w, h) tuples
        color:            RGB fill/stroke colour
    """
    base = Image.open(io.BytesIO(screenshot_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
 
    for x, y, w, h in boxes:
        x1, y1, x2, y2 = x, y, x + w, y + h
        draw.rectangle([x1, y1, x2, y2], outline=(*color, 220))
 
    annotated = Image.alpha_composite(base, overlay).convert("RGB")
    return annotated

 
if __name__ == "__main__":
    main()