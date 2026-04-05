"""
main.py - FastAPI application with all endpoints.
Phase 2: query accepts optional timestamp + frame_base64 for video-context queries.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Lecture AI TA Pipeline", version="2.0.0")

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static file serving ───────────────────────────────────────────────────────
from app.config import FRAMES_DIR, SLIDES_IMAGES_DIR  # noqa: E402

app.mount("/frames", StaticFiles(directory=str(FRAMES_DIR), html=False), name="frames")
app.mount("/slides", StaticFiles(directory=str(SLIDES_IMAGES_DIR), html=False), name="slides")

# Serve video + player from FastAPI so Range requests work (needed for seeking)
from app.config import DATA_DIR, PROJECT_ROOT  # noqa: E402
PLAYER_DIR = PROJECT_ROOT / "player"
PLAYER_DIR.mkdir(exist_ok=True)
app.mount("/player", StaticFiles(directory=str(PLAYER_DIR), html=True), name="player")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def _startup():
    from app.student.profile import init_db
    init_db()
    logger.info("Startup complete.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> list:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def _get_frame_manifest() -> list:
    from app.config import FRAME_MANIFEST
    return _load_json(FRAME_MANIFEST)


def _get_topic_segments() -> list:
    from app.config import TOPIC_SEGMENTS
    return _load_json(TOPIC_SEGMENTS)


def _get_slide_records() -> list:
    from app.config import SLIDES_IMAGES_DIR
    manifest = SLIDES_IMAGES_DIR / "slides_manifest.json"
    return _load_json(manifest)


# ── Request / Response models ─────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    student_id: str
    timestamp: Optional[float] = None       # video timestamp when paused (seconds)
    frame_base64: Optional[str] = None      # base64 JPEG of paused frame


class StudentCreateRequest(BaseModel):
    name: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/video/{filename}")
def stream_video(filename: str, request: Request):
    """Stream video with Range request support (needed for seeking)."""
    video_path = DATA_DIR / filename
    if not video_path.exists():
        # follow symlink manually
        video_path = video_path.resolve()
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    file_size = os.path.getsize(video_path)
    range_header = request.headers.get("range")

    if range_header:
        # Parse "bytes=start-end"
        range_spec = range_header.replace("bytes=", "").strip()
        parts = range_spec.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        def iter_chunk():
            with open(video_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk_size = min(1024 * 1024, remaining)  # 1MB chunks
                    data = f.read(chunk_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            iter_chunk(),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )
    else:
        def iter_full():
            with open(video_path, "rb") as f:
                while True:
                    data = f.read(1024 * 1024)
                    if not data:
                        break
                    yield data

        return StreamingResponse(
            iter_full(),
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )


@app.post("/process-lecture")
def process_lecture(background_tasks: BackgroundTasks):
    from app.processing.pipeline import run_pipeline
    try:
        result = run_pipeline()
        return result
    except Exception as exc:
        logger.exception("Pipeline error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/query")
def query(req: QueryRequest):
    """Main AI TA endpoint. Accepts optional timestamp + frame for video context."""
    from app.config import (
        ANTHROPIC_API_KEY,
        CLAUDE_MODEL,
        GUIDELINES_TXT,
        TOP_K_RESULTS,
    )
    from app.retrieval.vectorstore import query as chroma_query
    from app.retrieval.context_builder import build_context
    from app.agent.prompts import build_system_prompt, build_user_message
    from app.agent.claude_client import call_claude
    from app.agent.response_parser import parse_response
    from app.student.profile import get_student_profile, update_student_profile

    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not set.")

    # 0. Check for curated demo response (polished + reliable for key moments)
    from app.agent.demo_responses import match_demo
    demo = match_demo(req.question, req.timestamp)
    if demo:
        logger.info("Matched curated demo response for question=%r ts=%s", req.question, req.timestamp)
        # Still update student profile
        from app.student.profile import update_student_profile
        try:
            refs = demo.get("lecture_references", [])
            update_student_profile(
                student_id=req.student_id,
                question=req.question,
                topic=refs[0]["topic"] if refs else "",
                key_concepts=[],
            )
        except Exception:
            pass
        return demo

    # 1. Retrieve chunks from ChromaDB
    retrieved = chroma_query(req.question, top_k=TOP_K_RESULTS)

    # 2. Load student profile
    student_profile = get_student_profile(req.student_id)

    # 3. Load supporting data
    frame_manifest = _get_frame_manifest()
    slide_records = _get_slide_records()

    # 4. Build context (with timestamp boosting if provided)
    ctx = build_context(
        question=req.question,
        retrieved_chunks=retrieved,
        student_profile=student_profile,
        frame_manifest=frame_manifest,
        slide_records=slide_records,
        guidelines_path=GUIDELINES_TXT,
        timestamp=req.timestamp,
    )

    # 5. Build prompts
    system_prompt = build_system_prompt(
        guidelines_text=ctx["guidelines"],
        student_name=ctx["student_name"],
        past_topics=ctx["past_topics"],
        struggles=ctx["struggles"],
        interaction_count=ctx["interaction_count"],
    )
    user_message = build_user_message(
        question=req.question,
        retrieved_chunks_text=ctx["retrieved_chunks_text"],
        keyframe_descriptions=ctx["keyframe_descriptions"],
        slide_descriptions=ctx["slide_descriptions"],
        timestamp=req.timestamp,
        has_frame=bool(req.frame_base64),
    )

    # 6. Call LLM (with vision if frame provided)
    try:
        raw_response = call_claude(
            system_prompt=system_prompt,
            user_message=user_message,
            api_key=ANTHROPIC_API_KEY,
            model=CLAUDE_MODEL,
            frame_base64=req.frame_base64,
        )
    except Exception as exc:
        logger.exception("LLM API error: %s", exc)
        raise HTTPException(status_code=502, detail=f"LLM API error: {exc}")

    # 7. Parse structured response
    parsed = parse_response(
        raw_text=raw_response,
        frame_manifest=frame_manifest,
        topic_segments=ctx["topic_segments"],
    )

    # 8. Update student profile
    top_topic = ctx["topic_segments"][0]["topic"] if ctx["topic_segments"] else ""
    top_concepts = ctx["all_key_concepts"][:5]
    try:
        update_student_profile(
            student_id=req.student_id,
            question=req.question,
            topic=top_topic,
            key_concepts=top_concepts,
        )
    except Exception as exc:
        logger.warning("Could not update student profile: %s", exc)

    return {
        "answer": parsed["answer"],
        "annotations": parsed["annotations"],
        "highlights": parsed["highlights"],
        "referenced_images": parsed["referenced_images"],
        "lecture_references": parsed["lecture_references"],
        "student_profile_updated": True,
    }


@app.post("/student/{student_id}")
def create_student(student_id: str, req: StudentCreateRequest):
    from app.student.profile import create_or_update_student
    return create_or_update_student(student_id, req.name)


@app.get("/student/{student_id}/profile")
def get_student(student_id: str):
    from app.student.profile import get_student_profile
    return get_student_profile(student_id)


@app.get("/segments")
def get_segments():
    """Return topic segments for the player chapter navigation."""
    segments = _get_topic_segments()
    return [
        {
            "segment_id": s.get("segment_id", ""),
            "title": s.get("title", ""),
            "start_time": s.get("start_time", 0),
            "end_time": s.get("end_time", 0),
        }
        for s in segments
    ]
