"""
Decision model backends for the action predictor.

A :class:`DecisionModel` turns a prompt (chat messages + numbered candidates)
into a raw JSON decision string matching the schema in
:data:`action_predictor.prompting.SYSTEM_PROMPT`. Returning a raw string
lets a single ``parse_response`` path validate every backend identically.

Two backends are provided: :class:`RandomModel` (a dependency-free baseline)
and :class:`QwenModel` (a text-only Qwen LLM via ``transformers``). Both share
the same interface, so they are interchangeable in :class:`ActionPredictor`.
"""

from __future__ import annotations

import json
import logging
import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from action_predictor import Candidate

from .constants import (
    ACTIONS,
    DEFAULT_SYSTEM_PROMPT,
    ELEMENT_ACTIONS,
    SCROLL_DIRECTIONS,
)

logger = logging.getLogger(__name__)

# Default Qwen checkpoint (matches transformers_demo.py). Natively multimodal,
# but used text-only here.
DEFAULT_QWEN_MODEL = "Qwen/Qwen3.5-2B"


class DecisionModel(ABC):
    """Interface for a backend that turns a prompt into a raw JSON decision."""

    @abstractmethod
    def generate(self, prompt: str, candidates: list[Candidate]) -> str:
        """Return a raw JSON decision string for the given user prompt."""


class RandomModel(DecisionModel):
    """
    Baseline backend that emits a valid random decision.

    Ignores the prompt semantics: picks a random action and, for
    element-targeting actions, a random in-range candidate index. Element
    actions are only chosen when at least one candidate exists. Accepts an
    optional ``seed`` for deterministic tests.
    """

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def generate(self, prompt: str, candidates: list[Candidate]) -> str:
        if candidates:
            action = self._rng.choice(ACTIONS)
        else:
            # No selectable elements: only non-element actions are valid.
            action = self._rng.choice(
                [a for a in ACTIONS if a not in ELEMENT_ACTIONS]
            )

        decision: dict = {"action": action}
        if action in ELEMENT_ACTIONS:
            decision["index"] = self._rng.randrange(len(candidates))
        if action == "type":
            decision["text"] = self._rng.choice(
                ["hello", "search query", "example@test.com", "cats"]
            )
        elif action == "scroll":
            decision["direction"] = self._rng.choice(SCROLL_DIRECTIONS)
        elif action == "press_key":
            decision["key"] = self._rng.choice(["Enter", "Escape", "Tab"])
        return json.dumps(decision)


class LanguageDecisionModel(DecisionModel):
    """Abstract class for an LLM-based decision model abstracting model-agnostic methods."""
    def build_messages(self, user_prompt: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT):
        """Combine user prompt and system prompt."""
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

    @property
    def device(self):
        """Resolve the torch device lazily (auto-detect CUDA, else CPU)."""
        if self._device is None:
            import torch

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        return self._device


class QwenModel(LanguageDecisionModel):
    """
    Text-only decision backend backed by a Qwen model via ``transformers``.

    Follows the load/generate pattern of ``transformers_demo.py`` but feeds the
    action-prediction chat prompt (text only, no screenshot) and returns the
    model's raw text, which :func:`parse_response` then validates. Generation
    defaults to greedy decoding (``temperature=0``) so the JSON output is
    deterministic.

    The model and processor are loaded lazily on the first :meth:`generate`
    call (or via an explicit :meth:`load`), so importing this module and
    constructing the object stay cheap. A pre-loaded ``model``/``processor``
    pair may be injected (useful for tests) to bypass loading entirely.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_QWEN_MODEL,
        *,
        device: str | None = None,
        max_new_tokens: int = 128,
        temperature: float = 0.0,
        top_p: float = 0.9,
        model=None,
        processor=None,
    ):
        self.model_name = model_name
        self._device = device
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p
        self._model = model
        self._processor = processor

    def load(self) -> None:
        """Load the processor and model onto the target device (idempotent)."""
        if self._model is not None and self._processor is not None:
            return

        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        logger.info("Loading Qwen model %s on %s", self.model_name, self.device)
        if self._processor is None:
            self._processor = AutoProcessor.from_pretrained(self.model_name)
        if self._model is None:
            model = AutoModelForImageTextToText.from_pretrained(
                self.model_name,
                torch_dtype=torch.bfloat16,
                trust_remote_code=True,
            ).to(self.device)
            model.eval()
            self._model = model

    def _to_vl_messages(self, messages: list[dict]) -> list[dict]:
        """
        Convert plain-string chat messages into Qwen-VL structured content.

        ``build_messages`` produces ``{"role", "content": <str>}`` entries;
        Qwen-VL / ``process_vision_info`` expect ``content`` to be a list of
        typed blocks. Text-only here, so each string becomes a single
        ``{"type": "text", "text": ...}`` block. Already-structured content is
        passed through unchanged (so a screenshot block can be added later).
        """
        vl_messages = []
        for msg in messages:
            content = msg["content"]
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            vl_messages.append({"role": msg["role"], "content": content})
        return vl_messages

    def generate(self, prompt: str, candidates: list[Candidate]) -> str:
        """Run the chat prompt through Qwen and return its raw text output.

        ``candidates`` is part of the :class:`DecisionModel` interface but is
        unused here -- the prompt already embeds the numbered candidate list.
        """
        self.load()

        import torch
        from qwen_vl_utils import process_vision_info
        from transformers import GenerationConfig

        messages = self.build_messages(prompt)
        processor, model = self._processor, self._model
        vl_messages = self._to_vl_messages(messages)

        text_prompt = processor.apply_chat_template(
            vl_messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(vl_messages)

        inputs = processor(
            text=[text_prompt],
            images=image_inputs,
            videos=video_inputs,
            return_tensors="pt",
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        gen_config = GenerationConfig(
            max_new_tokens=self.max_new_tokens,
            do_sample=self.temperature > 0.0,
            temperature=self.temperature,
            top_p=self.top_p,
            pad_token_id=processor.tokenizer.pad_token_id,
            eos_token_id=processor.tokenizer.eos_token_id,
        )

        with torch.inference_mode():
            output_ids = model.generate(**inputs, generation_config=gen_config)

        prompt_len = inputs["input_ids"].shape[1]
        raw = processor.batch_decode(
            output_ids[:, prompt_len:],
            skip_special_tokens=True,
            clean_up_tokenization_spaces=True,
        )[0]
        return raw.strip()
