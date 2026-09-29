"""
System prompt, message building, and response parsing for the action predictor.

Two responsibilities live here:

* **Prompting** -- :data:`SYSTEM_PROMPT` (the task/schema description) and
  :func:`build_messages`, which assembles the chat messages fed to a
  ``DecisionModel``.
* **Parsing** -- :func:`parse_response`, which validates a model's raw JSON
  decision string against the numbered candidates and returns an
  :class:`~action_predictor.action_predictor.Action`, raising
  :class:`ActionParseError` on any malformed or invalid output.

Keeping both in one module co-locates the prompt with the parser that consumes
its output, so the schema described to the model and the schema enforced on the
response stay in sync.
"""

from __future__ import annotations

import json
import re

from .constants import (
    ACTIONS,
    SCROLL_DIRECTIONS,
)
from .models import Action, Candidate

# An opening-tag line: first non-space char is '<' followed by a tag name (not
# a closing '</' tag). Matches both leaf lines (<a ...>text</a>) and container
# open lines (<div ...>).
_OPEN_TAG_RE = re.compile(r"^<[A-Za-z]")

# Collapse the whitespace left behind after the marker is removed.
_WS_RE = re.compile(r"\s{2,}")

# Marker attribute that flags a line as an interactible candidate. It is only a
# selection marker, so it is stripped from the stored candidate text.
INTERACTIBLE_MARKER = 'data-interactible="true"'


class ActionParseError(ValueError):
    """Raised when a model response cannot be parsed into a valid Action."""


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> dict:
    """Extract the first JSON object from ``raw`` model output."""
    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        raise ActionParseError(f"No JSON object found in model output: {raw!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ActionParseError(f"Invalid JSON in model output: {raw!r}") from exc
    if not isinstance(data, dict):
        raise ActionParseError(f"Model output is not a JSON object: {raw!r}")
    return data


def _candidate_to_element(candidate: Candidate) -> dict:
    """Convert a Candidate into the Action.element dict."""
    return {"index": candidate.index, "text": candidate.text}


def parse_response(raw: str, candidates: list[Candidate]) -> Action:
    """
    Parse a raw model response into a validated :class:`Action`.

    Raises :class:`ActionParseError` on missing/invalid JSON, an unknown
    action, a missing/out-of-range index for element-targeting actions, or a
    missing required payload field.
    """
    data = _extract_json(raw)

    action = data.get("action")
    if action not in ACTIONS:
        raise ActionParseError(
            f"Unknown or missing action {action!r}; allowed: {ACTIONS}"
        )

    if action == "finish":
        return Action(action_type="finish")

    if action == "scroll":
        direction = data.get("direction")
        if direction not in SCROLL_DIRECTIONS:
            raise ActionParseError(
                f"scroll requires 'direction' in {SCROLL_DIRECTIONS}, got "
                f"{direction!r}"
            )
        return Action(action_type="scroll", direction=direction)

    if action == "press_key":
        key = data.get("key")
        if not key:
            raise ActionParseError("press_key requires a non-empty 'key'.")
        return Action(action_type="press_key", key=str(key))

    # Element-targeting actions: click, type, hover.
    index = data.get("index")
    if not isinstance(index, int) or isinstance(index, bool):
        raise ActionParseError(f"{action} requires an integer 'index', got {index!r}")
    if not 0 <= index < len(candidates):
        raise ActionParseError(
            f"{action} index {index} out of range (0..{len(candidates) - 1})"
        )
    element = _candidate_to_element(candidates[index])

    if action == "type":
        text = data.get("text")
        if text is None:
            raise ActionParseError("type requires a 'text' field.")
        return Action(action_type="type", element=element, text=str(text))

    return Action(action_type=action, element=element)


def build_user_prompt(candidate_text: str, action_description: str) -> str:
    """
    Build the chat-template message list for the decision model.

    Returns a system message describing the action schema and a user message
    embedding the numbered candidate list and the natural-language action.
    """
    user_content = (
        f"Interactible elements:\n{candidate_text}\n\n"
        f"Action to perform: {action_description}"
    )
    return user_content


def _strip_marker(line: str) -> str:
    """Remove the data-interactible marker and tidy leftover whitespace."""
    without = line.replace(INTERACTIBLE_MARKER, "")
    without = _WS_RE.sub(" ", without)
    # Fix a possible ``<tag >`` or ``< tag`` artifact from marker removal.
    return without.replace(" >", ">").replace("< ", "<").strip()


def parse_candidates(pseudo_html: str) -> list[Candidate]:
    """
    Index interactible elements from the pretty-printed pseudo-HTML, by line.

    Preprocessing is purely line-based: each line that opens a new element
    (starts with ``<tag`` -- not a closing ``</tag>`` line) *and* carries the
    ``data-interactible="true"`` marker becomes a numbered candidate. The
    marker is stripped from the stored text. Candidates are numbered in
    document order starting at 0.
    """
    candidates: list[Candidate] = []
    for raw_line in pseudo_html.splitlines():
        line = raw_line.strip()
        if not _OPEN_TAG_RE.match(line):
            continue
        if INTERACTIBLE_MARKER not in line:
            continue
        candidates.append(Candidate(index=len(candidates), text=_strip_marker(line)))
    return candidates


# --- Rendering and prompt building -----------------------------------------


def render_candidates(candidates: list[Candidate]) -> str:
    """Render candidates as a compact ``[index] text`` listing, one per line."""
    return "\n".join(f"[{c.index}] {c.text}" for c in candidates)

