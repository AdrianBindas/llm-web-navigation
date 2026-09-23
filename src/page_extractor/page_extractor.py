import io
import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from .browser_session import BrowserSession
from .constants import (
    COMPUTED_STYLE_KEYS,
    OUTPUT_DIR,
    VIEWPORT,
)
from .html_builder import HtmlBuilder
from .modification_rules import (
    CleanEmpty,
    KeepAttrs,
    StripInternalAttrs,
    StripTags,
    UnwrapHidden,
    UnwrapUnkept,
)
from .snapshot_parser import SnapshotParser

logger = logging.getLogger(__name__)


def default_rules():
    """
    Build the default ordered rule list. Order matters: strip unwanted tags,
    unwrap hidden, unwrap non-qualifying wrappers, restrict and truncate
    attributes, drop leftover empties, then strip scaffolding. Each rule bakes
    in its own default data sets; callers may reorder, remove, append, or
    replace rules with custom-parameterized instances.
    """
    return [
        StripTags(),
        UnwrapHidden(),
        UnwrapUnkept(),
        KeepAttrs(),
        CleanEmpty(),
        StripInternalAttrs(),
    ]


def apply_rules(soup, parser, rules):
    """Run each rule over the soup in order, returning the final soup."""
    for rule in rules:
        soup = rule(soup, parser)
    return soup


@dataclass
class OutputConfig:
    """
    Customizable output behavior for the extractor. Relative html_path /
    annotated_path are resolved against output_dir (the project root by default),
    so output does not depend on the current working directory. Absolute paths
    are used as-is.
    """
    prettify: bool = True
    stdout: bool = False
    html_path: str = "playwright_soup.txt"
    unique_boxes: bool = True
    box_color: tuple = (0, 200, 80)
    annotated_path: str = "images/annotated_screenshot.png"
    output_dir: object = OUTPUT_DIR


class OutputWriter:
    """Writes the filtered HTML, extracts boxes, and annotates the screenshot."""

    def __init__(self, config=None):
        self.config = config or OutputConfig()

    def _resolve(self, path):
        """Resolve a path against output_dir (unless already absolute) and
        ensure its parent directory exists."""
        p = Path(path)
        if not p.is_absolute():
            p = Path(self.config.output_dir) / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def write_html(self, soup):
        text = soup.prettify() if self.config.prettify else str(soup)
        if self.config.html_path:
            with open(self._resolve(self.config.html_path), "w", encoding="utf-8") as f:
                f.write(text)
        if self.config.stdout:
            print(text)
        return text

    def extract_boxes(self, soup):
        """Collect (x, y, w, h) int tuples from every data-bounds attribute."""
        boxes = []
        for tag in soup.find_all(True):
            bounds_str = tag.get("data-bounds")
            if not bounds_str:
                continue
            try:
                x, y, w, h = (int(v) for v in bounds_str.split(","))
            except ValueError:
                continue
            boxes.append((x, y, w, h))
        if self.config.unique_boxes:
            seen = set()
            unique = []
            for box in boxes:
                if box not in seen:
                    seen.add(box)
                    unique.append(box)
            return unique
        return boxes

    def annotate(self, screenshot_bytes, boxes):
        base = Image.open(io.BytesIO(screenshot_bytes)).convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        color = self.config.box_color
        for x, y, w, h in boxes:
            draw.rectangle([x, y, x + w, y + h], outline=(*color, 220))
        return Image.alpha_composite(base, overlay).convert("RGB")

    def save_annotated(self, screenshot_bytes, boxes):
        image = self.annotate(screenshot_bytes, boxes)
        if self.config.annotated_path:
            image.save(self._resolve(self.config.annotated_path))
        return image


@dataclass
class ExtractionResult:
    """Bundle of everything produced by a PageExtractor run."""
    snapshot: dict
    parser: SnapshotParser
    soup: object
    html: str
    boxes: list
    annotated_image: object = None


class PageExtractor:
    """
    Orchestrates the full pipeline: open browser -> capture snapshot + screenshot
    -> parse -> build full tree -> apply filter rules -> write output + annotate.
    Every stage is customizable: pass a rule list, an OutputConfig, or browser
    kwargs.
    """

    def __init__(self, rules=None, output_config=None, browser_kwargs=None,
                 viewport=None, computed_style_keys=None):
        self.rules = rules if rules is not None else default_rules()
        self.output = OutputWriter(output_config)
        self.browser_kwargs = browser_kwargs or {}
        self.viewport = viewport or dict(VIEWPORT)
        self.computed_style_keys = computed_style_keys or list(COMPUTED_STYLE_KEYS)

    def parse(self, snapshot):
        return SnapshotParser(snapshot, self.viewport, self.computed_style_keys)

    def build_soup(self, parser):
        soup = HtmlBuilder(parser).to_soup()
        return apply_rules(soup, parser, self.rules)

    def run(self, url):
        with BrowserSession(
            viewport=self.viewport,
            computed_style_keys=self.computed_style_keys,
            **self.browser_kwargs,
        ) as session:
            session.open(url)
            screenshot_bytes = session.screenshot()
            snapshot = session.capture_snapshot()

        parser = self.parse(snapshot)
        soup = self.build_soup(parser)
        html = self.output.write_html(soup)
        boxes = self.output.extract_boxes(soup)
        logger.info("Found %d bounding boxes.", len(boxes))
        annotated = self.output.save_annotated(screenshot_bytes, boxes)

        return ExtractionResult(
            snapshot=snapshot,
            parser=parser,
            soup=soup,
            html=html,
            boxes=boxes,
            annotated_image=annotated,
        )
