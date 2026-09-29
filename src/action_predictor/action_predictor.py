"""
Model-based action prediction over page_extractor pseudo-HTML.

Given the pseudo-HTML produced by the page_extractor (tags carrying
``data-bounds`` and ``data-interactible`` attributes) and a natural-language
description of what to do, an :class:`ActionPredictor` decides on a concrete
action (click, type, scroll, hover, press_key, finish) and, when relevant, the
specific target element.

The decision itself is produced by a pluggable ``DecisionModel`` (see
:mod:`action_predictor.models`). The model returns a small JSON decision
string; the predictor parses and validates it against the numbered
interactible candidates. Only ``RandomModel`` is implemented for now; a real
LLM backend (e.g. Qwen) can be added later behind the same interface without
touching the parsing/prompting pipeline.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import DecisionModel
from .decision_models import RandomModel
from .models import Action
from .parse_utils import (
    build_user_prompt,
    parse_candidates,
    parse_response,
    render_candidates,
)

logger = logging.getLogger(__name__)


class ActionPredictor:
    """
    Orchestrates candidate parsing, prompting, model decision, and parsing.

    The decision backend is pluggable via the ``model`` argument (any
    ``DecisionModel``), defaulting to ``RandomModel`` so the predictor runs
    with no heavy dependencies.
    """

    def __init__(self, model: DecisionModel | None = None):
        if model is None:
            model = RandomModel()
        self.model = model

    def predict(self, pseudo_html: str, action_description: str) -> Action:
        """
        Predict the next :class:`Action` for the given page and instruction.

        Runs: parse candidates -> render -> build user prompt ->
        model.generate -> parse_response. Raises :class:`ActionParseError` if
        the model's output is invalid.
        """
        candidates = parse_candidates(pseudo_html)
        candidate_text = render_candidates(candidates)
        user_prompt = build_user_prompt(candidate_text, action_description)
        raw = self.model.generate(user_prompt, candidates)
        logger.debug("Model decision: %s", raw)
        return parse_response(raw, candidates)
