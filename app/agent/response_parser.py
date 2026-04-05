"""
response_parser.py - Parses structured SPOKEN / ANNOTATIONS / HIGHLIGHT response
from the LLM, plus legacy [SHOW_IMAGE:] and [LECTURE_REF:] tag extraction.
"""

import re
import logging

logger = logging.getLogger(__name__)

_IMAGE_TAG = re.compile(r"\[SHOW_IMAGE:([^\]]+)\]")
_LECTURE_TAG = re.compile(r"\[LECTURE_REF:([\d.]+)s?\]")

_SPOKEN_RE = re.compile(r"===SPOKEN===\s*(.*?)(?====|\Z)", re.DOTALL)
_ANNOTATIONS_RE = re.compile(r"===ANNOTATIONS===\s*(.*?)(?====|\Z)", re.DOTALL)
_HIGHLIGHT_RE = re.compile(r"===HIGHLIGHT===\s*(.*?)(?====|\Z)", re.DOTALL)


def _parse_highlight(raw: str):
    """Parse 'x1,y1,x2,y2' string into a dict. Returns None on failure."""
    try:
        parts = [float(v.strip()) for v in raw.strip().split(",")]
        if len(parts) == 4:
            x1, y1, x2, y2 = parts
            # Sanity-check: all values 0–1, x2>x1, y2>y1
            if all(0.0 <= v <= 1.0 for v in parts) and x2 > x1 and y2 > y1:
                return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
    except (ValueError, TypeError):
        pass
    return None


def _find_lecture_refs(raw_text: str, topic_segments: list) -> list:
    ref_timestamps = [float(t) for t in _LECTURE_TAG.findall(raw_text)]
    refs = []
    for ts in ref_timestamps:
        matched = None
        for seg in topic_segments:
            if seg.get("start_time", 0) <= ts <= seg.get("end_time", 0):
                matched = seg
                break
        if matched is None and topic_segments:
            matched = min(topic_segments, key=lambda s: abs(s.get("start_time", 0) - ts))
        if matched:
            refs.append({
                "topic": matched.get("topic", matched.get("title", "Unknown")),
                "start_time": matched.get("start_time", ts),
                "end_time": matched.get("end_time", ts),
            })
    return refs


def parse_response(
    raw_text: str,
    frame_manifest: list,
    topic_segments: list,
) -> dict:
    """
    Parse LLM response. Handles both:
      - New structured format (===SPOKEN=== / ===ANNOTATIONS=== / ===HIGHLIGHT===)
      - Legacy format (plain text with [SHOW_IMAGE:] / [LECTURE_REF:] tags)

    Returns:
        {
            "answer": str,               # clean spoken/answer text
            "annotations": [str],        # list of annotation lines
            "highlights": dict|None,     # {x1,y1,x2,y2} or None
            "referenced_images": [...],
            "lecture_references": [...],
        }
    """
    spoken_match = _SPOKEN_RE.search(raw_text)
    annotations_match = _ANNOTATIONS_RE.search(raw_text)
    highlight_match = _HIGHLIGHT_RE.search(raw_text)

    if spoken_match:
        # ── Structured format ─────────────────────────────────────────────────
        answer = spoken_match.group(1).strip()

        annotations = []
        if annotations_match:
            raw_ann = annotations_match.group(1).strip()
            annotations = [
                line.strip().lstrip("•-– ").strip()
                for line in raw_ann.splitlines()
                if line.strip() and line.strip() not in ("", "•", "-")
            ]

        highlight = None
        if highlight_match:
            highlight = _parse_highlight(highlight_match.group(1))

        # Still extract any legacy image/lecture tags that may appear
        lecture_refs = _find_lecture_refs(raw_text, topic_segments)
        if not lecture_refs and topic_segments:
            for seg in topic_segments[:2]:
                lecture_refs.append({
                    "topic": seg.get("topic", seg.get("title", "Unknown")),
                    "start_time": seg.get("start_time", 0),
                    "end_time": seg.get("end_time", 0),
                })

        # Extract image refs from annotations text
        frame_by_name = {f["filename"]: f for f in frame_manifest}
        image_filenames = _IMAGE_TAG.findall(raw_text)
        referenced_images = []
        for fn in image_filenames:
            fn = fn.strip()
            frame = frame_by_name.get(fn)
            referenced_images.append({
                "path": f"/frames/{fn}",
                "timestamp": frame.get("timestamp", 0) if frame else 0,
                "description": frame.get("description", "") if frame else "",
            })

        return {
            "answer": answer,
            "annotations": annotations,
            "highlights": highlight,
            "referenced_images": referenced_images,
            "lecture_references": lecture_refs,
        }

    else:
        # ── Legacy format fallback ────────────────────────────────────────────
        image_filenames = _IMAGE_TAG.findall(raw_text)
        frame_by_name = {f["filename"]: f for f in frame_manifest}
        referenced_images = []
        for fn in image_filenames:
            fn = fn.strip()
            frame = frame_by_name.get(fn)
            referenced_images.append({
                "path": f"/frames/{fn}",
                "timestamp": frame.get("timestamp", 0) if frame else 0,
                "description": frame.get("description", "") if frame else "",
            })

        lecture_refs = _find_lecture_refs(raw_text, topic_segments)
        if not lecture_refs and topic_segments:
            for seg in topic_segments[:2]:
                lecture_refs.append({
                    "topic": seg.get("topic", seg.get("title", "Unknown")),
                    "start_time": seg.get("start_time", 0),
                    "end_time": seg.get("end_time", 0),
                })

        answer = _IMAGE_TAG.sub("", raw_text)
        answer = _LECTURE_TAG.sub("", answer).strip()

        # Auto-generate simple annotations from answer (first 4 sentences)
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', answer) if s.strip()]
        annotations = sentences[:4]

        return {
            "answer": answer,
            "annotations": annotations,
            "highlights": None,
            "referenced_images": referenced_images,
            "lecture_references": lecture_refs,
        }
