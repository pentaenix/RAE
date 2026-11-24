from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

from ...core.util import sanitize_component
from .audio_archives import AUDIO_EXTENSIONS, AUDIO_MAGICS, get_sdat_file, iter_sdat_files, iter_swar_swavs, sdat_sound_symbols
from .audio_sequences import render_sequences
from .audio_pcm import decode_strm_pcm, decode_swav_pcm



def export_audio_bundle(asset, out_dir: str | Path, *, make_mp3: bool = False) -> list[Path]:
    """Export lossless audio pieces and WAV previews where DSM can decode them.

    WAV is the best-quality practical output for PCM/sample previews because it is
    lossless. MP3 is optional and only created when ffmpeg is available.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    stem = sanitize_component(Path(asset.virtual_path).stem or asset.asset_id)
    bundle = out / f"{stem}_{asset.asset_id}"
    bundle.mkdir(parents=True, exist_ok=True)

    raw_path = bundle / f"raw{asset.extension or '.bin'}"
    raw_path.write_bytes(asset.data)
    written.append(raw_path)

    manifest = {
        "sourcePath": asset.virtual_path,
        "magic": asset.magic,
        "kind": asset.kind,
        "notes": [],
        "children": [],
    }

    if asset.magic == "SDAT":
        children = iter_sdat_files(asset.data)
        manifest["sounds"] = sdat_sound_symbols(asset.data)
        names = {item["fileId"]: item["name"] for item in manifest["sounds"] if item["kind"] != "SSAR"}
        for child in children:
            child_dir = bundle / "sdat_files"
            child_dir.mkdir(exist_ok=True)
            child_name = child.path
            if child.index in names:
                child_name = f"{child.index:04d}_{sanitize_component(names[child.index])}{Path(child.path).suffix}"
            path = child_dir / child_name
            path.write_bytes(child.data)
            written.append(path)
            child_record = {
                "index": child.index,
                "path": child.path,
                "magic": child.magic,
                "offset": child.offset,
                "size": child.size,
                "exported": str(path.relative_to(bundle)),
            }
            if child.magic == "SWAR":
                swavs = iter_swar_swavs(child.data)
                swav_dir = child_dir / f"{Path(child_name).stem}_swav"
                for swav in swavs:
                    swav_dir.mkdir(exist_ok=True)
                    swav_path = swav_dir / sanitize_component(swav.path)
                    swav_path.write_bytes(swav.data)
                    written.append(swav_path)
                    wav = try_write_wav(swav.data, swav_dir / (swav_path.stem + ".wav"))
                    if wav:
                        written.append(wav)
                child_record["swavCount"] = len(swavs)
            elif child.magic in {"SWAV", "STRM"}:
                wav = try_write_wav(child.data, child_dir / (Path(child_name).stem + ".wav"))
                if wav:
                    written.append(wav)
                    child_record["wav"] = str(wav.relative_to(bundle))
            manifest["children"].append(child_record)
        manifest["notes"].append("Use Browse Nintendo DS sounds on the source SDAT to render named SSEQ/SSAR entries with their original banks.")
    elif asset.magic == "SWAR":
        swavs = iter_swar_swavs(asset.data)
        for swav in swavs:
            swav_path = bundle / sanitize_component(swav.path)
            swav_path.write_bytes(swav.data)
            written.append(swav_path)
            wav = try_write_wav(swav.data, bundle / (swav_path.stem + ".wav"))
            if wav:
                written.append(wav)
        manifest["children"].append({"swavCount": len(swavs)})
    elif asset.magic in {"SWAV", "STRM"}:
        wav = try_write_wav(asset.data, bundle / f"{stem}.wav")
        if wav:
            written.append(wav)
        else:
            manifest["notes"].append("RAE could not safely decode this audio payload yet; raw original was exported losslessly.")
    else:
        manifest["notes"].append("This raw asset may depend on other members of its SDAT. Open the parent SDAT to render named sequences.")

    if make_mp3:
        mp3_paths = write_mp3_copies([p for p in written if p.suffix.lower() == ".wav"], bundle)
        written.extend(mp3_paths)
        if mp3_paths:
            manifest["mp3"] = [str(p.relative_to(bundle)) for p in mp3_paths]
        else:
            manifest["notes"].append("MP3 requested, but ffmpeg was not available or conversion failed. WAV previews are lossless and preferred for quality.")

    manifest_path = bundle / "audio_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    written.append(manifest_path)
    return written


def write_mp3_copies(wav_paths: list[Path], bundle: Path) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return []
    out_dir = bundle / "mp3"
    out_dir.mkdir(exist_ok=True)
    written: list[Path] = []
    for wav_path in wav_paths:
        mp3 = (out_dir / wav_path.relative_to(bundle)).with_suffix(".mp3")
        mp3.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "0", str(mp3)]
        try:
            proc = subprocess.run(cmd, text=True, capture_output=True)
        except Exception:
            continue
        if proc.returncode == 0 and mp3.exists():
            written.append(mp3)
    return written


def try_write_wav(data: bytes, out_path: str | Path) -> Path | None:
    if data.startswith(b"SWAV"):
        pcm = decode_swav_pcm(data)
    elif data.startswith(b"STRM"):
        pcm = decode_strm_pcm(data)
    else:
        pcm = None
    if pcm is None:
        return None
    sample_rate, channels, sample_width, pcm_bytes = pcm
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return out


def export_sounds(data: bytes, entries: list[dict], output: Path) -> list[Path]:
    sequences = [entry for entry in entries if entry["kind"] in {"SSEQ", "SSAR"}]
    written = render_sequences(data, sequences, output) if sequences else []
    direct = [entry for entry in entries if entry["kind"] in {"SWAR", "STRM"}]
    if not direct:
        return written
    for sound in direct:
        source = get_sdat_file(data, sound["fileId"])
        if source is None or source.magic != sound["kind"]:
            raise RuntimeError(f"Missing data for {sound['name']}.")
        folder = output / f"{sound['kind']}_{sound['index']:04d}_{sanitize_component(sound['name'])}"
        waves = iter_swar_swavs(source.data) if source.magic == "SWAR" else [source]
        sample = sound.get("sampleIndex")
        if sample is not None:
            waves = [entry for entry in waves if entry.index == sample]
        decoded = []
        for entry in waves:
            name = sanitize_component(sound["name"])
            suffix = f"_{entry.index:04d}" if source.magic == "SWAR" else ""
            decoded.append(try_write_wav(entry.data, folder / f"{name}{suffix}.wav"))
        if not decoded or any(path is None for path in decoded):
            raise RuntimeError(f"Could not decode all samples in {sound['name']}.")
        written.extend(decoded)
    return written
