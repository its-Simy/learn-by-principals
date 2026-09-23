"""Pull a JSON array out of a model's answer (code fences, prose, ``[n]`` citation markers)."""

from __future__ import annotations

import json
import re
from typing import Any

_CITATION = re.compile(r"\[\d+(?:,\s*\d+)*\]")


def extract_json_array(text: str) -> list[Any] | None:
    """The first JSON array in ``text``, or None. ``[]`` counts as an array."""
    for candidate in (text, _CITATION.sub("", text)):
        for start in [m.start() for m in re.finditer(r"\[\s*[\{\]]", candidate)]:
            try:
                value, _ = json.JSONDecoder().raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, list):
                return value
    return None
