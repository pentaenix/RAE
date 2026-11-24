"""Resolve model-local animation resources inside large Nitro cutscene archives."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Iterable

from ...core.assets import Asset
from .asset_resolver import MODEL_ANIMATION_MAGICS
from .nitro_names import extract_nitro_names


_NUMBERED_FILE_RE = re.compile(r"^file_(\d+)(?:\.bin)?(?:\.[^.]+)?$", re.IGNORECASE)


def _archive_index(asset: Asset) -> int | None:
    match = _NUMBERED_FILE_RE.match(PurePosixPath(asset.virtual_path).name)
    return int(match.group(1)) if match else None


def _normalized_names(asset: Asset) -> set[str]:
    return {name.casefold() for name in extract_nitro_names(asset.data) if name}


def named_animation_siblings(
    model: Asset,
    assets: Iterable[Asset],
    *,
    max_distance: int = 8,
    limit: int = 16,
) -> list[Asset]:
    """Return nearby animations whose Nitro target name matches ``model``.

    Gen 5's large cutscene NARCs place many independent BCA/BMA/BMD/BTA sets in
    one folder. Folder-wide sibling selection therefore attaches unrelated clips.
    Their animation dictionaries repeat the owning model name, which is a safer
    and deterministic bundle boundary.
    """
    if model.magic != "BMD0":
        return []
    model_index = _archive_index(model)
    if model_index is None:
        return []
    model_names = _normalized_names(model)
    if not model_names:
        return []

    matches: list[tuple[int, int, str, Asset]] = []
    for candidate in assets:
        if candidate.asset_id == model.asset_id:
            continue
        if candidate.magic not in MODEL_ANIMATION_MAGICS:
            continue
        if candidate.folder_key != model.folder_key:
            continue
        candidate_index = _archive_index(candidate)
        if candidate_index is None:
            continue
        distance = abs(candidate_index - model_index)
        if distance > max_distance:
            continue
        overlap = model_names & _normalized_names(candidate)
        if not overlap:
            continue
        matches.append((distance, candidate_index, candidate.virtual_path, candidate))

    matches.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in matches[:limit]]
