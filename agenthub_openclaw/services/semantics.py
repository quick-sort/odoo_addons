"""OpenClaw reply semantics: think-block stripping and stream accumulation."""

import re

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text):
    """Return ``(visible, think_parts)``.

    ``visible`` is ``text`` with every ``<think>...</think>`` block removed;
    ``think_parts`` is the list of raw stripped think blocks.
    """
    text = text or ""
    think_parts = _THINK_RE.findall(text)
    visible = _THINK_RE.sub("", text).strip()
    return visible, think_parts


def accumulate_stream(frames):
    """Fold a list of stream frames into one accumulated text.

    Each frame is a dict with ``content`` (str) and ``finish`` (bool). Returns
    ``(text, finished)``; ``finished`` is the last frame's flag.
    """
    parts = []
    finished = False
    for frame in frames:
        parts.append(frame.get("content", ""))
        finished = bool(frame.get("finish", False))
    return "".join(parts), finished
