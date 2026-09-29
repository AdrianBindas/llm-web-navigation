"""
Demo: predict a browser action from page_extractor pseudo-HTML.

Uses the RandomModel backend (no heavy model download) against the pseudo-HTML
the page_extractor previously wrote to ``playwright_soup.txt``. Run with:

    python action_predictor_demo.py
"""

import sys
from pathlib import Path

from action_predictor import ActionPredictor, RandomModel, parse_candidates

# The extractor output can contain non-ASCII text (e.g. CJK); make sure printing
# it does not fail on a non-UTF-8 console (common on Windows).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PSEUDO_HTML_PATH = Path(__file__).resolve().parent / "playwright_soup.txt"
ACTION_DESCRIPTION = "Search for cats"


def main() -> None:
    pseudo_html = PSEUDO_HTML_PATH.read_text(encoding="utf-8")

    candidates = parse_candidates(pseudo_html)
    print(f"Parsed {len(candidates)} interactible candidates.")

    predictor = ActionPredictor(model=RandomModel(seed=0))
    action = predictor.predict(pseudo_html, ACTION_DESCRIPTION)

    print(f"Action description: {ACTION_DESCRIPTION!r}")
    print(f"Predicted action: {action}")


if __name__ == "__main__":
    main()
