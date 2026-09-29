"""
Deterministic tests for the action_predictor module.

Exercise candidate parsing/numbering, prompt building, response parsing and
index mapping, the RandomModel backend, and the ActionPredictor pipeline
without loading any heavy model.
"""

import json

import pytest

from action_predictor import (
    ACTIONS,
    ELEMENT_ACTIONS,
    Action,
    ActionParseError,
    ActionPredictor,
    Candidate,
    DecisionModel,
    QwenModel,
    RandomModel,
    build_user_prompt,
    parse_candidates,
    parse_response,
    render_candidates,
)
from action_predictor.constants import DEFAULT_SYSTEM_PROMPT
from action_predictor.decision_models import DEFAULT_QWEN_MODEL

# A small pseudo-HTML sample in the page_extractor pretty-printed shape: one
# element per line. Interactible lines carry data-interactible="true"; the
# plain span and the closing/container lines do not qualify as candidates.
SAMPLE_HTML = """\
<body data-bounds="0,0,1280,900" data-interactible="true">
 <a data-bounds="48,24,28,16" data-interactible="true" href="/home">Home</a>
 <span data-bounds="200,24,60,16">Plain text</span>
 <input data-bounds="456,12,300,40" data-interactible="true" placeholder="Search" type="text"></input>
 <button data-bounds="800,12,40,40" data-interactible="true">Go</button>
</body>
"""


# --- parse_candidates ------------------------------------------------------


def test_parse_candidates_only_interactible():
    candidates = parse_candidates(SAMPLE_HTML)
    # body, a, input, button carry the marker; the plain span and closing
    # </body> line do not.
    starts = [c.text.split()[0].lstrip("<").rstrip(">") for c in candidates]
    assert starts == ["body", "a", "input", "button"]
    assert "span" not in starts


def test_parse_candidates_sequential_indices():
    candidates = parse_candidates(SAMPLE_HTML)
    assert [c.index for c in candidates] == list(range(len(candidates)))


def test_parse_candidates_strips_interactible_marker():
    candidates = parse_candidates(SAMPLE_HTML)
    # The marker is only a selection flag; it must not appear in stored text.
    for c in candidates:
        assert "data-interactible" not in c.text


def test_parse_candidates_text_is_the_line():
    candidates = parse_candidates(SAMPLE_HTML)
    by_start = {c.text.split()[0].lstrip("<"): c.text for c in candidates}
    # The <a> line is preserved verbatim (minus the marker), attrs + bounds.
    assert by_start["a"] == '<a data-bounds="48,24,28,16" href="/home">Home</a>'
    assert 'placeholder="Search"' in by_start["input"]
    assert 'type="text"' in by_start["input"]


def test_parse_candidates_ignores_closing_and_text_lines():
    html = "<div data-interactible=\"true\">\n plain text line\n</div>"
    candidates = parse_candidates(html)
    # Only the opening <div> line qualifies.
    assert len(candidates) == 1
    assert candidates[0].text == "<div>"


def test_parse_candidates_empty():
    assert parse_candidates("<div>no interactible here</div>") == []


# --- render_candidates -----------------------------------------------------


def test_render_candidates_contains_index_and_text():
    candidates = parse_candidates(SAMPLE_HTML)
    rendered = render_candidates(candidates)
    for c in candidates:
        assert f"[{c.index}] {c.text}" in rendered
    assert "/home" in rendered


# --- build_user_prompt -----------------------------------------------------


def test_build_user_prompt_embeds_candidates_and_action():
    prompt = build_user_prompt("[0] <a> Home", "click home")
    assert isinstance(prompt, str)
    assert "click home" in prompt
    assert "[0] <a> Home" in prompt


def test_system_prompt_enumerates_all_actions():
    for action in ACTIONS:
        assert action in DEFAULT_SYSTEM_PROMPT


# --- parse_response --------------------------------------------------------


@pytest.fixture
def candidates():
    return parse_candidates(SAMPLE_HTML)


def test_parse_response_click(candidates):
    action = parse_response(json.dumps({"action": "click", "index": 1}), candidates)
    assert action.action_type == "click"
    assert action.element["index"] == 1
    assert action.element["text"].startswith("<a")
    assert 'data-bounds="48,24,28,16"' in action.element["text"]


def test_parse_response_type(candidates):
    raw = json.dumps({"action": "type", "index": 2, "text": "cats"})
    action = parse_response(raw, candidates)
    assert action.action_type == "type"
    assert action.text == "cats"
    assert action.element["text"].startswith("<input")


def test_parse_response_hover(candidates):
    action = parse_response(json.dumps({"action": "hover", "index": 3}), candidates)
    assert action.action_type == "hover"
    assert action.element["text"].startswith("<button")


def test_parse_response_scroll(candidates):
    action = parse_response(
        json.dumps({"action": "scroll", "direction": "down"}), candidates
    )
    assert action.action_type == "scroll"
    assert action.direction == "down"
    assert action.element is None


def test_parse_response_press_key(candidates):
    action = parse_response(
        json.dumps({"action": "press_key", "key": "Enter"}), candidates
    )
    assert action.action_type == "press_key"
    assert action.key == "Enter"


def test_parse_response_finish(candidates):
    action = parse_response(json.dumps({"action": "finish"}), candidates)
    assert action.action_type == "finish"
    assert action.element is None


def test_parse_response_extracts_json_from_noise(candidates):
    raw = 'Sure! Here is the decision:\n{"action": "click", "index": 0}\nDone.'
    action = parse_response(raw, candidates)
    assert action.action_type == "click"
    assert action.element["index"] == 0


def test_parse_response_index_out_of_range_raises(candidates):
    with pytest.raises(ActionParseError):
        parse_response(json.dumps({"action": "click", "index": 99}), candidates)


def test_parse_response_missing_index_raises(candidates):
    with pytest.raises(ActionParseError):
        parse_response(json.dumps({"action": "click"}), candidates)


def test_parse_response_bool_index_raises(candidates):
    # bool is a subclass of int but must not be accepted as an index.
    with pytest.raises(ActionParseError):
        parse_response(json.dumps({"action": "click", "index": True}), candidates)


def test_parse_response_unknown_action_raises(candidates):
    with pytest.raises(ActionParseError):
        parse_response(json.dumps({"action": "teleport"}), candidates)


def test_parse_response_no_json_raises(candidates):
    with pytest.raises(ActionParseError):
        parse_response("no json here", candidates)


def test_parse_response_invalid_json_raises(candidates):
    with pytest.raises(ActionParseError):
        parse_response("{action: click,}", candidates)


def test_parse_response_type_missing_text_raises(candidates):
    with pytest.raises(ActionParseError):
        parse_response(json.dumps({"action": "type", "index": 2}), candidates)


def test_parse_response_scroll_bad_direction_raises(candidates):
    with pytest.raises(ActionParseError):
        parse_response(
            json.dumps({"action": "scroll", "direction": "sideways"}), candidates
        )


# --- RandomModel -----------------------------------------------------------


def test_random_model_output_always_parses(candidates):
    # Run many seeds; every random decision must parse into a valid Action.
    for seed in range(50):
        model = RandomModel(seed=seed)
        raw = model.generate("", candidates)
        action = parse_response(raw, candidates)
        assert action.action_type in ACTIONS


def test_random_model_is_reproducible(candidates):
    a = RandomModel(seed=42).generate("", candidates)
    b = RandomModel(seed=42).generate("", candidates)
    assert a == b


def test_random_model_element_action_index_in_range(candidates):
    # Force many draws and check any element action carries an in-range index.
    for seed in range(100):
        raw = RandomModel(seed=seed).generate("", candidates)
        data = json.loads(raw)
        if data["action"] in ELEMENT_ACTIONS:
            assert 0 <= data["index"] < len(candidates)


def test_random_model_no_candidates_avoids_element_actions():
    empty: list[Candidate] = []
    for seed in range(50):
        raw = RandomModel(seed=seed).generate("", empty)
        data = json.loads(raw)
        assert data["action"] not in ELEMENT_ACTIONS


# --- ActionPredictor -------------------------------------------------------


def test_predictor_default_random_runs_end_to_end():
    predictor = ActionPredictor(model=RandomModel(seed=0))
    action = predictor.predict(SAMPLE_HTML, "search for cats")
    assert isinstance(action, Action)
    assert action.action_type in ACTIONS


def test_predictor_default_backend_is_random():
    assert isinstance(ActionPredictor().model, RandomModel)


class _StubModel(DecisionModel):
    """Returns a fixed decision, ignoring the prompt."""

    def __init__(self, decision: dict):
        self._decision = decision

    def generate(self, prompt, candidates):
        return json.dumps(self._decision)


def test_predictor_with_stub_model():
    predictor = ActionPredictor(model=_StubModel({"action": "click", "index": 1}))
    action = predictor.predict(SAMPLE_HTML, "go home")
    assert action.action_type == "click"
    assert action.element["text"].startswith("<a")


def test_predictor_propagates_parse_errors():
    predictor = ActionPredictor(model=_StubModel({"action": "click", "index": 999}))
    with pytest.raises(ActionParseError):
        predictor.predict(SAMPLE_HTML, "go home")


# --- QwenModel -------------------------------------------------------------


def test_qwen_model_default_name():
    assert QwenModel().model_name == DEFAULT_QWEN_MODEL


def test_qwen_model_construction_is_lazy():
    # Constructing must not import torch/transformers (kept out of sys.modules
    # unless already loaded by another test). We assert the object is built
    # without invoking load().
    qwen = QwenModel()
    assert isinstance(qwen, DecisionModel)
    assert qwen._model is None and qwen._processor is None


def test_qwen_build_messages_structure():
    messages = QwenModel().build_messages("[0] <a>")
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == DEFAULT_SYSTEM_PROMPT
    assert messages[1]["content"] == "[0] <a>"


def test_qwen_to_vl_messages_wraps_text():
    messages = QwenModel().build_messages(build_user_prompt("[0] <a>", "click home"))
    vl = QwenModel()._to_vl_messages(messages)
    assert [m["role"] for m in vl] == ["system", "user"]
    for m in vl:
        assert isinstance(m["content"], list)
        assert m["content"][0]["type"] == "text"
    assert "click home" in vl[1]["content"][0]["text"]


def test_qwen_to_vl_messages_passthrough_structured():
    structured = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    vl = QwenModel()._to_vl_messages(structured)
    assert vl == structured


# --- Optional real-model integration (opt-in: --run-qwen) ------------------


@pytest.mark.qwen
def test_qwen_model_real_integration():
    from action_predictor import ActionPredictor, QwenModel

    predictor = ActionPredictor(model=QwenModel(max_new_tokens=64))
    action = predictor.predict(SAMPLE_HTML, "click the home link")
    assert action.action_type in ACTIONS
