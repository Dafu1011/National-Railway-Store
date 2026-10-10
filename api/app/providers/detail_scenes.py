from __future__ import annotations

from typing import Any


DETAIL_SCENE_KEYS = tuple(f"scene_{index}" for index in range(1, 5))
DETAIL_SCENE_MAX_LENGTH = 500


def normalize_scene_inputs(value: Any) -> dict[str, str]:
    """Keep fixed slot identities while discarding only blank descriptions."""
    if not isinstance(value, dict) or any(key not in DETAIL_SCENE_KEYS for key in value):
        raise ValueError("DETAIL_SCENE_INPUT_INVALID: expected scene_1 through scene_4 text fields")
    result: dict[str, str] = {}
    for key in DETAIL_SCENE_KEYS:
        if key not in value:
            continue
        text = value[key]
        if not isinstance(text, str):
            raise ValueError(f"DETAIL_SCENE_INPUT_INVALID: {key} must be text")
        text = text.strip()
        if len(text) > DETAIL_SCENE_MAX_LENGTH:
            raise ValueError(f"DETAIL_SCENE_INPUT_INVALID: {key} exceeds {DETAIL_SCENE_MAX_LENGTH} characters")
        if text:
            result[key] = text
    return result
