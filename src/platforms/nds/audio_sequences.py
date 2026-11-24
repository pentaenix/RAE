"""Render Nintendo DS sequences with the original archive's banks and samples."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from collections import defaultdict
from pathlib import Path

from .audio_archives import sdat_sound_symbols


def dualrip_executable() -> str | None:
    configured = os.environ.get("RAE_DUALRIP")
    if configured:
        return shutil.which(configured)
    cached = Path(__file__).resolve().parents[3] / ".cache" / "tools" / (
        "dualrip.exe" if os.name == "nt" else "dualrip")
    return shutil.which("dualrip") or shutil.which(str(cached))


def render_sequences(data: bytes, selections: list[dict], destination: Path) -> list[Path]:
    tool = dualrip_executable()
    if tool is None:
        raise RuntimeError("Install the DualRip CLI on PATH or set RAE_DUALRIP to its executable.")
    valid = {(s["kind"], s.get("archiveIndex"), s["index"]) for s in sdat_sound_symbols(data)}
    groups: dict[int | None, list[int]] = defaultdict(list)
    for sound in selections:
        kind, archive, index = sound["kind"], sound.get("archiveIndex"), sound["index"]
        if kind not in {"SSEQ", "SSAR"} or (kind, archive, index) not in valid:
            raise ValueError("Selected sequence is missing from the SDAT archive.")
        if index not in groups[archive]:
            groups[archive].append(index)

    with tempfile.TemporaryDirectory(prefix="rae-nds-audio-") as temp:
        work = Path(temp)
        sdat = work / "sound.sdat"
        sdat.write_bytes(data)
        files: list[tuple[Path, Path]] = []
        for archive, indices in groups.items():
            label = "SSEQ" if archive is None else f"SSAR_{archive:04d}"
            folder = work / label
            args = ["--sequence", *map(str, indices)] if archive is None else [
                "--archive", str(archive), "--only", *map(str, indices)]
            try:
                result = subprocess.run([tool, "--file", str(sdat), "--out", str(folder), *args],
                                        capture_output=True, text=True, errors="replace", timeout=300)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"DualRip could not finish rendering {label}: {exc}") from exc
            if result.returncode:
                raise RuntimeError(f"DualRip failed for {label}: {(result.stderr or result.stdout).strip()[-1200:]}")
            wavs = sorted(folder.rglob("*.wav"))
            if len(wavs) != len(indices):
                raise RuntimeError(f"DualRip rendered {len(wavs)} of {len(indices)} selected {label} sounds.")
            for path in wavs:
                with wave.open(str(path), "rb") as wav:
                    if wav.getnframes() == 0 or not wav.readframes(1):
                        raise RuntimeError(f"DualRip produced an empty WAV for {path.stem}.")
                files.append((path, destination / label / path.name))

        for source, target in files:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        return [target for _, target in files]
