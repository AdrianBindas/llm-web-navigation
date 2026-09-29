from dataclasses import dataclass


@dataclass
class Candidate:
    """
    One numbered, interactible element extracted from the pseudo-HTML.

    ``index`` is the stable handle the model uses to refer to this element.
    ``text`` is the element's pseudo-HTML line as it appears in the extractor
    output (tag, attributes such as ``data-bounds``/``href``, and any inline
    text), trimmed of indentation and with the ``data-interactible`` marker
    removed -- everything the model needs to identify it lives in this string.
    """

    index: int
    text: str = ""


@dataclass
class Action:
    """
    A predicted action returned by :meth:`ActionPredictor.predict`.

    ``element`` is a plain dict ``{"index", "text"}`` describing the selected
    candidate for element-targeting actions, otherwise ``None``. The
    action-specific payload lives in ``text`` (for ``type``), ``direction``
    (for ``scroll``) or ``key`` (for ``press_key``).
    """

    action_type: str
    element: dict | None = None
    text: str | None = None
    direction: str | None = None
    key: str | None = None

