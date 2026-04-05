"""
pipeline.py - Orchestrates all processing steps in order.

Can be run as a standalone script:
    python -m app.processing.pipeline [--force-proportional]

Or triggered via POST /process-lecture.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_pipeline(force_proportional: bool = False) -> dict:
    """
    Execute the full processing pipeline.

    Returns a summary dict with counts for the API response.
    """
    from app.config import (
        ANTHROPIC_API_KEY,
        AUDIO_WAV,
        CLAUDE_MODEL,
        CHROMA_PERSIST_DIR,
        DATA_DIR,
        FRAME_MANIFEST,
        FRAMES_DIR,
        GUIDELINES_TXT,
        LECTURE_VIDEO,
        SLIDES_IMAGES_DIR,
        SLIDES_PDF,
        TIMESTAMPED_TRANSCRIPT,
        TOPIC_SEGMENTS,
        TRANSCRIPT_TXT,
        WHISPER_FALLBACK_MODEL,
        WHISPER_MODEL,
        WHISPER_TIMEOUT_SECONDS,
    )

    summary = {
        "status": "success",
        "segments_created": 0,
        "frames_extracted": 0,
        "slides_processed": 0,
        "errors": [],
    }

    # ── Step 1: Transcription ─────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 1: Transcript alignment (Whisper)")
    logger.info("=" * 60)
    try:
        from app.processing.transcription import run_transcription
        ts_segments = run_transcription(
            video_path=LECTURE_VIDEO,
            transcript_path=TRANSCRIPT_TXT,
            output_path=TIMESTAMPED_TRANSCRIPT,
            whisper_model=WHISPER_MODEL,
            fallback_model=WHISPER_FALLBACK_MODEL,
            timeout=WHISPER_TIMEOUT_SECONDS,
            force_proportional=force_proportional,
        )
        logger.info("Step 1 complete: %d transcript segments", len(ts_segments))
    except Exception as exc:
        logger.exception("Step 1 (transcription) failed: %s", exc)
        summary["errors"].append(f"transcription: {exc}")
        ts_segments = []

    if not ts_segments:
        logger.error("No timestamped segments; cannot proceed with segmentation.")
        summary["status"] = "partial"

    # ── Step 2: Topic segmentation ────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2: Claude topic segmentation")
    logger.info("=" * 60)
    topic_segments = []
    try:
        from app.processing.segmentation import run_segmentation
        topic_segments = run_segmentation(
            timestamped_path=TIMESTAMPED_TRANSCRIPT,
            output_path=TOPIC_SEGMENTS,
            api_key=ANTHROPIC_API_KEY,
            model=CLAUDE_MODEL,
        )
        summary["segments_created"] = len(topic_segments)
        logger.info("Step 2 complete: %d topic segments", len(topic_segments))
    except Exception as exc:
        logger.exception("Step 2 (segmentation) failed: %s", exc)
        summary["errors"].append(f"segmentation: {exc}")
        summary["status"] = "partial"

    # ── Step 3: Keyframe extraction ───────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 3: Keyframe extraction")
    logger.info("=" * 60)
    frame_manifest = []
    try:
        from app.processing.keyframes import run_keyframe_extraction
        if topic_segments:
            frame_manifest = run_keyframe_extraction(
                video_path=LECTURE_VIDEO,
                topic_segments=topic_segments,
                frames_dir=FRAMES_DIR,
                manifest_path=FRAME_MANIFEST,
                api_key=ANTHROPIC_API_KEY,
                model=CLAUDE_MODEL,
                describe_visuals=False,  # skip per-frame vision calls to save time
            )
            summary["frames_extracted"] = len(frame_manifest)
            logger.info("Step 3 complete: %d frames", len(frame_manifest))
        else:
            logger.warning("No topic segments; skipping keyframe extraction.")
    except Exception as exc:
        logger.exception("Step 3 (keyframes) failed: %s", exc)
        summary["errors"].append(f"keyframes: {exc}")

    # ── Step 4: Slide processing ──────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 4: Slide processing")
    logger.info("=" * 60)
    slide_records = []
    try:
        from app.processing.slides import run_slide_processing
        slide_records = run_slide_processing(
            pdf_path=SLIDES_PDF,
            slides_dir=SLIDES_IMAGES_DIR,
            api_key=ANTHROPIC_API_KEY,
            model=CLAUDE_MODEL,
            describe=True,
        )
        summary["slides_processed"] = len(slide_records)
        logger.info("Step 4 complete: %d slides", len(slide_records))
    except Exception as exc:
        logger.exception("Step 4 (slides) failed: %s", exc)
        summary["errors"].append(f"slides: {exc}")

    # ── Step 5: ChromaDB ingestion ────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 5: ChromaDB ingestion")
    logger.info("=" * 60)
    try:
        from app.retrieval.vectorstore import ingest_data
        ingest_data(
            topic_segments=topic_segments,
            frame_manifest=frame_manifest,
            slide_records=slide_records,
            timestamped_segments=_load_json(TIMESTAMPED_TRANSCRIPT),
        )
        logger.info("Step 5 complete: ChromaDB ingestion done.")
    except Exception as exc:
        logger.exception("Step 5 (ChromaDB) failed: %s", exc)
        summary["errors"].append(f"chromadb: {exc}")
        summary["status"] = "partial"

    if not summary["errors"]:
        summary["status"] = "success"

    logger.info("Pipeline complete. Summary: %s", summary)
    return summary


def _load_json(path: Path) -> list:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the lecture processing pipeline.")
    parser.add_argument(
        "--force-proportional",
        action="store_true",
        help="Skip Whisper and use proportional timestamp estimation.",
    )
    args = parser.parse_args()

    result = run_pipeline(force_proportional=args.force_proportional)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 1)
