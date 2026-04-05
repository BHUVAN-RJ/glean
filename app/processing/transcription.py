"""
transcription.py - Whisper timestamping with proportional fallback.

Produces data/timestamped_transcript.json:
[{"start": float, "end": float, "text": str}, ...]
"""

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _extract_audio(video_path: Path, audio_path: Path) -> bool:
    """Extract mono 16kHz WAV from video using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(audio_path),
    ]
    logger.info("Extracting audio: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg audio extraction failed:\n%s", result.stderr)
        return False
    return True


def _get_video_duration(video_path: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        logger.warning("Could not parse video duration, assuming 7200s")
        return 7200.0


def _run_whisper(audio_path: Path, model: str, output_dir: Path) -> Optional[list]:
    """
    Run Whisper on audio_path, return list of segment dicts or None on failure.
    Saves a JSON sidecar at output_dir / audio_path.stem + .json.
    """
    try:
        import whisper  # type: ignore
    except ImportError:
        logger.error("openai-whisper is not installed.")
        return None

    logger.info("Loading Whisper model '%s'…", model)
    model_obj = whisper.load_model(model)

    logger.info("Transcribing with Whisper (word_timestamps=True)…")
    result = model_obj.transcribe(
        str(audio_path),
        word_timestamps=True,
        verbose=False,
    )

    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"].strip(),
        })

    # persist raw Whisper JSON alongside audio
    raw_path = output_dir / "whisper_raw.json"
    with open(raw_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info("Whisper raw output saved to %s", raw_path)

    return segments


def _run_whisper_with_timeout(
    audio_path: Path,
    model: str,
    output_dir: Path,
    timeout: int,
) -> Optional[list]:
    """Run Whisper in a thread; return None if it exceeds timeout."""
    result_holder: dict = {"segments": None, "error": None}

    def _worker():
        try:
            result_holder["segments"] = _run_whisper(audio_path, model, output_dir)
        except Exception as exc:
            result_holder["error"] = str(exc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        logger.warning("Whisper timed out after %ds", timeout)
        return None
    if result_holder["error"]:
        logger.error("Whisper error: %s", result_holder["error"])
        return None
    return result_holder["segments"]


def proportional_fallback(transcript_path: Path, video_duration: float) -> list:
    """
    Estimate timestamps proportionally.
    Each non-empty line gets start = (line_idx / total_lines) * duration.
    """
    logger.info("Using proportional timestamp fallback…")
    lines = [l.rstrip() for l in transcript_path.read_text(encoding="utf-8").splitlines()]
    non_empty = [l for l in lines if l.strip()]
    total = max(len(non_empty), 1)

    segments = []
    for idx, text in enumerate(non_empty):
        start = (idx / total) * video_duration
        end = ((idx + 1) / total) * video_duration
        segments.append({"start": round(start, 2), "end": round(end, 2), "text": text})

    logger.info("Proportional fallback produced %d segments", len(segments))
    return segments


def run_transcription(
    video_path: Path,
    transcript_path: Path,
    output_path: Path,
    whisper_model: str = "medium",
    fallback_model: str = "base",
    timeout: int = 1200,
    force_proportional: bool = False,
) -> list:
    """
    Main entry point for transcript alignment.

    Priority:
      1. Load from output_path if it already exists.
      2. If force_proportional, skip directly to proportional fallback.
      3. Try Whisper medium (with timeout).
      4. If timeout hit, try Whisper base.
      5. Proportional fallback if everything fails.
    """
    # ── Already processed ────────────────────────────────────────────────────
    if output_path.exists():
        logger.info("Timestamped transcript already exists at %s, loading.", output_path)
        with open(output_path) as f:
            return json.load(f)

    video_duration = _get_video_duration(video_path)
    logger.info("Video duration: %.1fs", video_duration)

    # ── Forced proportional ──────────────────────────────────────────────────
    if force_proportional:
        segments = proportional_fallback(transcript_path, video_duration)
        _save(segments, output_path)
        return segments

    # ── Extract audio ────────────────────────────────────────────────────────
    audio_path = output_path.parent / "audio.wav"
    if not audio_path.exists():
        if not video_path.exists():
            logger.error("Lecture video not found at %s", video_path)
            segments = proportional_fallback(transcript_path, video_duration)
            _save(segments, output_path)
            return segments
        if not _extract_audio(video_path, audio_path):
            logger.error("Audio extraction failed, using proportional fallback")
            segments = proportional_fallback(transcript_path, video_duration)
            _save(segments, output_path)
            return segments

    # ── Whisper medium ────────────────────────────────────────────────────────
    logger.info("Attempting Whisper model='%s' with %ds timeout…", whisper_model, timeout)
    segments = _run_whisper_with_timeout(audio_path, whisper_model, output_path.parent, timeout)

    # ── Whisper base fallback ─────────────────────────────────────────────────
    if segments is None and whisper_model != fallback_model:
        logger.warning("Falling back to Whisper model='%s'…", fallback_model)
        segments = _run_whisper_with_timeout(
            audio_path, fallback_model, output_path.parent, timeout
        )

    # ── Proportional fallback ─────────────────────────────────────────────────
    if segments is None:
        logger.warning("All Whisper attempts failed; using proportional fallback.")
        segments = proportional_fallback(transcript_path, video_duration)

    _save(segments, output_path)
    return segments


def _save(segments: list, path: Path) -> None:
    with open(path, "w") as f:
        json.dump(segments, f, indent=2)
    logger.info("Saved %d segments to %s", len(segments), path)
