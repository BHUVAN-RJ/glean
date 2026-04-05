"""
segmentation.py - Claude API topic segmentation.

Reads data/timestamped_transcript.json, sends 20-min windows to Claude,
and produces data/topic_segments.json.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_SEGMENTATION_PROMPT = """\
You are analyzing a Multimedia Systems (CSCI 576) lecture transcript.
Identify distinct topic segments in this transcript excerpt.
For each segment, provide:
1. A short descriptive title (e.g., "Sampling Period and Frequency Tradeoffs")
2. A 2-3 sentence summary of what is taught
3. The start and end timestamps (in seconds, as floats)
4. Key terms and concepts mentioned
5. Whether the professor draws a diagram or references a visual (look for phrases like \
"as you can see", "look at this", "let me draw", "on this slide", "on the screen")

Return ONLY a valid JSON array with no extra text before or after:
[{{
  "title": "...",
  "summary": "...",
  "start_time": float,
  "end_time": float,
  "key_concepts": ["..."],
  "has_visual_reference": bool,
  "visual_cue_timestamps": [float]
}}]
"""


def _build_window_text(segments: list, start_idx: int, end_idx: int) -> str:
    """Format a slice of transcript segments as readable text for Claude."""
    lines = []
    for seg in segments[start_idx:end_idx]:
        lines.append(f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}")
    return "\n".join(lines)


def _call_claude(client: OpenAI, window_text: str, model: str) -> Optional[list]:
    """Call the LLM with one transcript window; return parsed JSON list or None."""
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": _SEGMENTATION_PROMPT + "\n\nTRANSCRIPT EXCERPT:\n" + window_text,
                }
            ],
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # Remove control characters that break JSON parsing
        raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw)

        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse error from LLM segmentation: %s", exc)
        return None
    except Exception as exc:
        logger.error("LLM API error during segmentation: %s", exc)
        return None


def _windows(segments: list, window_sec: int, overlap_sec: int):
    """
    Yield (start_idx, end_idx) pairs covering the full transcript in
    overlapping time windows.
    """
    if not segments:
        return
    total_duration = segments[-1]["end"]
    win_start = 0.0
    while win_start < total_duration:
        win_end = win_start + window_sec
        # find segment indices whose start time falls in [win_start, win_end)
        idxs = [
            i for i, s in enumerate(segments)
            if win_start <= s["start"] < win_end
        ]
        if not idxs:
            win_start += window_sec - overlap_sec
            continue
        yield idxs[0], idxs[-1] + 1
        win_start += window_sec - overlap_sec


def _merge_segments(all_segments: list) -> list:
    """
    Merge topic segments from overlapping windows.
    De-duplicate by removing segments whose start_time falls within an
    already-accepted segment (keeps the first occurrence).
    """
    if not all_segments:
        return []

    # Sort by start_time
    all_segments.sort(key=lambda s: s.get("start_time", 0))

    merged = []
    for seg in all_segments:
        if merged and seg["start_time"] < merged[-1]["end_time"] - 30:
            # Overlap: skip duplicate; extend end_time if this one goes further
            if seg["end_time"] > merged[-1]["end_time"]:
                merged[-1]["end_time"] = seg["end_time"]
        else:
            merged.append(seg)

    return merged


def run_segmentation(
    timestamped_path: Path,
    output_path: Path,
    api_key: str,
    model: str,
    window_sec: int = 1200,
    overlap_sec: int = 120,
) -> list:
    """
    Main entry point.

    Loads timestamped transcript, runs Claude segmentation on 20-min windows,
    merges results, writes topic_segments.json, and returns the list.
    """
    if output_path.exists():
        logger.info("Topic segments already exist at %s, loading.", output_path)
        with open(output_path) as f:
            return json.load(f)

    with open(timestamped_path) as f:
        segments = json.load(f)

    if not segments:
        logger.error("No segments found in %s", timestamped_path)
        return []

    client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)
    all_topic_segments: list = []

    for win_num, (start_idx, end_idx) in enumerate(
        _windows(segments, window_sec, overlap_sec), start=1
    ):
        window_text = _build_window_text(segments, start_idx, end_idx)
        logger.info(
            "Segmenting window %d (segments %d–%d, %.0fs–%.0fs)…",
            win_num, start_idx, end_idx,
            segments[start_idx]["start"], segments[end_idx - 1]["end"],
        )

        result = _call_claude(client, window_text, model)
        if result:
            all_topic_segments.extend(result)
            logger.info("  → %d topics found in window %d", len(result), win_num)
        else:
            logger.warning("  → No topics extracted for window %d", win_num)

        # Respect rate limits
        time.sleep(1)

    merged = _merge_segments(all_topic_segments)
    logger.info("Total topic segments after merging: %d", len(merged))

    # Add sequential IDs
    for i, seg in enumerate(merged):
        seg["segment_id"] = f"seg_{i:03d}"

    with open(output_path, "w") as f:
        json.dump(merged, f, indent=2)
    logger.info("Topic segments saved to %s", output_path)

    return merged
