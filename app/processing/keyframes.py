"""
keyframes.py - ffmpeg keyframe extraction.

Extracts frames at:
  - segment start
  - segment midpoint
  - visual cue timestamps (from segmentation)

Produces data/frames/*.jpg and data/frame_manifest.json.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _extract_frame(
    video_path: Path,
    timestamp: float,
    output_path: Path,
) -> bool:
    """Extract a single frame at `timestamp` seconds from `video_path`."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Frame extraction failed at %.1fs: %s", timestamp, result.stderr[-300:])
        return False
    return True


def _describe_frame(
    image_path: Path,
    client: OpenAI,
    model: str,
) -> str:
    """Ask the vision model to describe a lecture frame. Returns a short string."""
    import base64
    try:
        data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
        suffix = image_path.suffix.lower().lstrip(".")
        media_type = "image/jpeg" if suffix == "jpg" else f"image/{suffix}"

        response = client.chat.completions.create(
            model=model,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{data}",
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Briefly describe what is shown in this lecture frame. "
                                "Is it a slide, a hand-drawn diagram, the professor speaking, "
                                "or something else? If it's a diagram or slide, describe the "
                                "key content in 1-2 sentences."
                            ),
                        },
                    ],
                }
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("Frame description failed for %s: %s", image_path.name, exc)
        return ""


def run_keyframe_extraction(
    video_path: Path,
    topic_segments: list,
    frames_dir: Path,
    manifest_path: Path,
    api_key: str,
    model: str,
    describe_visuals: bool = True,
) -> list:
    """
    Main entry point.

    For each topic segment extract:
      - Frame at start time
      - Frame at midpoint
      - Frames at each visual_cue_timestamp

    Returns the manifest (list of frame dicts).
    """
    if manifest_path.exists():
        logger.info("Frame manifest already exists at %s, loading.", manifest_path)
        with open(manifest_path) as f:
            return json.load(f)

    if not video_path.exists():
        logger.error("Video not found at %s, skipping keyframe extraction.", video_path)
        return []

    client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL) if (describe_visuals and api_key) else None

    manifest: list = []

    for seg in topic_segments:
        seg_id = seg.get("segment_id", "seg_unknown")
        start = float(seg.get("start_time", 0))
        end = float(seg.get("end_time", start + 60))
        mid = (start + end) / 2.0
        has_visual = seg.get("has_visual_reference", False)
        cue_times = seg.get("visual_cue_timestamps", [])

        # Build list of (timestamp, label) to extract
        timestamps_to_extract = [
            (start, "start"),
            (mid, "mid"),
        ]
        for ct in cue_times:
            timestamps_to_extract.append((float(ct), "cue"))

        for ts, label in timestamps_to_extract:
            safe_ts = int(ts)
            filename = f"frame_{seg_id}_{label}_{safe_ts}.jpg"
            out_path = frames_dir / filename

            if out_path.exists():
                logger.debug("Frame %s already exists, skipping.", filename)
            else:
                success = _extract_frame(video_path, ts, out_path)
                if not success:
                    continue

            description = ""
            if client and (has_visual or label == "cue") and out_path.exists():
                description = _describe_frame(out_path, client, model)

            manifest.append({
                "filename": filename,
                "segment_id": seg_id,
                "timestamp": ts,
                "label": label,
                "description": description,
                "topic_title": seg.get("title", ""),
            })

    logger.info("Extracted %d frames total", len(manifest))

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Frame manifest saved to %s", manifest_path)

    return manifest
