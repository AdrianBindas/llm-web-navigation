from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from bs4 import BeautifulSoup, Comment

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


def apply_stealth(page):
    Stealth().apply_stealth_sync(page)

def get_visible_with_bounds(snapshot):
    doc = snapshot["documents"][0]
    layout = doc.get("layout", {})
    node_indices = layout.get("nodeIndex", [])
    bounds = layout.get("bounds", [])
 
    visible = {}
    for i, node_id in enumerate(node_indices):
        if i >= len(bounds):
            continue
        x, y, w, h = bounds[i]
        if w > 0 and h > 0:
            visible[node_id] = (x, y, w, h)
 
    return visible
 
 
def snapshot_to_html_with_layout(snapshot):
    doc = snapshot["documents"][0]
    nodes = doc["nodes"]
    layout = doc.get("layout", {})
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
            root = i
        else:
            children[parent].append(i)
 
    if root is None:
        root = 0
 
    layout_map = {}
    visible_map = get_visible_with_bounds(snapshot)
 
    if layout:
        for i, node_idx in enumerate(layout.get("nodeIndex", [])):
            bounds = layout.get("bounds", [])
            if i < len(bounds):
                layout_map[node_idx] = bounds[i]
 
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
 
        if node_id in visible_map:
            x, y, w, h = visible_map[node_id]
            parts.append(f'data-bounds="{x:.0f},{y:.0f},{w:.0f},{h:.0f}"')
        elif node_id in layout_map:
            parts.append('data-visible="false"')
 
        return (" " + " ".join(parts)) if parts else ""
 
    def build(node_id):
        name_idx = node_names[node_id]
        node_type = node_types[node_id]
        value = get_string(node_values[node_id])
 
        # TEXT_NODE — keep non-empty text
        if node_type == 3:
            text = value.strip()
            return text if text else ""
 
        # COMMENT_NODE — drop
        if node_type == 8:
            return ""
 
        # DOCUMENT_NODE
        if node_type == 9:
            return "".join(build(child) for child in children[node_id])
 
        # ELEMENT_NODE
        if node_type == 1:
            name = get_string(name_idx).lower()
 
            # Drop non-content tags entirely
            if name in STRIP_TAGS:
                return ""
 
            is_visible = node_id in visible_map
            has_layout = node_id in layout_map
            if has_layout and not is_visible:
                inner = "".join(build(child) for child in children[node_id])
                return inner if inner.strip() else ""
 
            attrs = get_attrs(node_id)
            inner = "".join(build(child) for child in children[node_id])

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
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="Europe/Bratislava",
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
 
        page = context.new_page()
 
        apply_stealth(page)
 
        page.goto("https://tiktok.com/", wait_until="networkidle", timeout=60000)
  
        client = page.context.new_cdp_session(page)
        snapshot = client.send("DOMSnapshot.captureSnapshot", {
            "computedStyles": [],
        })
 
        html = snapshot_to_html_with_layout(snapshot)
        soup = BeautifulSoup(html, "html.parser")
        soup = clean_soup(soup)
 
        print(soup.prettify())
 
        browser.close()
 
 
if __name__ == "__main__":
    main()
