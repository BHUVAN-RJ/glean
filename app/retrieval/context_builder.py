"""
context_builder.py - Assembles the full context payload for Claude.

Given ChromaDB results + student profile + frame manifest, produces the
text blocks that go into the user message.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _load_guidelines(guidelines_path: Path) -> str:
    if guidelines_path.exists():
        return guidelines_path.read_text(encoding="utf-8").strip()
    return "No specific guidelines provided. Use sound pedagogical judgment."


def _keyframe_descriptions(
    segment_ids: list,
    frame_manifest: list,
) -> str:
    """Build a text block listing keyframes available for given segment IDs."""
    relevant = [
        f for f in frame_manifest
        if f.get("segment_id") in segment_ids
    ]
    if not relevant:
        return "No keyframe images available for these segments."

    lines = []
    for frame in relevant:
        desc = frame.get("description", "")
        ts = frame.get("timestamp", 0)
        fn = frame.get("filename", "")
        topic = frame.get("topic_title", "")
        lines.append(
            f"- [{fn}] at {ts:.1f}s (topic: {topic})"
            + (f": {desc}" if desc else "")
        )
    return "\n".join(lines)


def _slide_descriptions(slide_records: list, key_concepts: list) -> str:
    """Return slide descriptions that match key concepts (loose text match)."""
    if not slide_records:
        return ""

    concepts_lower = [c.lower() for c in key_concepts]
    matched = []
    for slide in slide_records:
        desc = slide.get("description", "").lower()
        if any(c in desc for c in concepts_lower):
            matched.append(slide)

    if not matched:
        # Just take the first few slides as fallback
        matched = slide_records[:3]

    lines = []
    for slide in matched[:5]:
        fn = slide.get("filename", "")
        desc = slide.get("description", "")
        lines.append(f"- [{fn}] {desc[:200]}")
    return "\n".join(lines)


def _boost_by_timestamp(chunks: list, timestamp: float) -> list:
    """
    Re-rank chunks so that segments whose time range contains `timestamp`
    appear first. Others are ordered by ChromaDB distance (original order).
    """
    containing = []
    nearby = []
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        start = meta.get("start_time", 0)
        end = meta.get("end_time", 0)
        if start <= timestamp <= end:
            containing.append(chunk)
        else:
            nearby.append(chunk)
    return containing + nearby


def build_context(
    question: str,
    retrieved_chunks: list,
    student_profile: dict,
    frame_manifest: list,
    slide_records: list,
    guidelines_path: Path,
    timestamp: float = None,
) -> dict:
    """
    Assemble context for a Claude API call.

    Returns:
        {
            "guidelines": str,
            "student_name": str,
            "past_topics": str,
            "struggles": str,
            "interaction_count": int,
            "retrieved_chunks_text": str,
            "keyframe_descriptions": str,
            "slide_descriptions": str,
            "segment_ids": [str],
            "topic_segments": [dict],  # for lecture_references
        }
    """
    guidelines = _load_guidelines(guidelines_path)

    # Boost by timestamp if provided
    if timestamp is not None:
        retrieved_chunks = _boost_by_timestamp(retrieved_chunks, timestamp)

    # Student profile
    student_name = student_profile.get("name", "Student")
    past_topics = student_profile.get("past_topics", [])
    struggles = student_profile.get("struggles", [])
    interaction_count = student_profile.get("total_interactions", 0)

    past_topics_str = ", ".join(past_topics) if past_topics else "None yet"
    struggles_str = (
        "; ".join(
            f"{s['concept']}: {s.get('details', '')}" for s in struggles
        )
        if struggles
        else "None identified"
    )

    # Retrieved chunk text
    chunk_lines = []
    segment_ids = []
    all_key_concepts = []
    topic_segments_for_refs = []

    for chunk in retrieved_chunks:
        meta = chunk.get("metadata", {})
        seg_id = chunk.get("id", "")
        segment_ids.append(seg_id)

        title = meta.get("topic_title", "Unknown Topic")
        summary = meta.get("summary", "")
        start = meta.get("start_time", 0)
        end = meta.get("end_time", 0)
        concepts = meta.get("key_concepts", "")
        doc = chunk.get("document", "")

        if concepts:
            all_key_concepts.extend([c.strip() for c in concepts.split(",")])

        chunk_lines.append(
            f"[SEGMENT: {title} | {start:.0f}s–{end:.0f}s]\n"
            f"Summary: {summary}\n"
            f"Key concepts: {concepts}\n"
            f"Transcript excerpt: {doc[:800]}\n"
        )

        topic_segments_for_refs.append({
            "topic": title,
            "start_time": start,
            "end_time": end,
            "segment_id": seg_id,
        })

    retrieved_chunks_text = "\n---\n".join(chunk_lines) if chunk_lines else "No relevant context found."

    # Keyframes
    keyframe_text = _keyframe_descriptions(segment_ids, frame_manifest)

    # Slides
    slide_text = _slide_descriptions(slide_records, all_key_concepts)

    return {
        "guidelines": guidelines,
        "student_name": student_name,
        "past_topics": past_topics_str,
        "struggles": struggles_str,
        "interaction_count": interaction_count,
        "retrieved_chunks_text": retrieved_chunks_text,
        "keyframe_descriptions": keyframe_text,
        "slide_descriptions": slide_text,
        "segment_ids": segment_ids,
        "topic_segments": topic_segments_for_refs,
        "all_key_concepts": all_key_concepts,
    }
