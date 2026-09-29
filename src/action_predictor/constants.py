# Allowed action vocabulary.
ACTIONS = ("click", "type", "scroll", "hover", "press_key", "finish")

# Actions that must target a specific candidate element (by index).
ELEMENT_ACTIONS = ("click", "type", "hover")

# Scroll directions considered valid.
SCROLL_DIRECTIONS = ("up", "down")

DEFAULT_SYSTEM_PROMPT = (
    "You control a web browser. You are given a list of numbered interactible "
    "elements from the current page and a description of the action to perform. "
    "Decide on a single next action.\n\n"
    "Respond with ONLY a JSON object, no other text. Schema:\n"
    '  {"action": <action>, "index": <int>, "text": <str>, '
    '"direction": <str>, "key": <str>}\n\n'
    "Allowed actions and their required fields:\n"
    '  - "click": requires "index" of the element to click.\n'
    '  - "type": requires "index" of the input element and "text" to type.\n'
    '  - "hover": requires "index" of the element to hover.\n'
    '  - "scroll": requires "direction" ("up" or "down"). No index.\n'
    '  - "press_key": requires "key" (e.g. "Enter"). No index.\n'
    '  - "finish": the task is complete. No other fields.\n\n'
    "Omit fields that do not apply to the chosen action."
)
