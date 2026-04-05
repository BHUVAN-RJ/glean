"""
config.py - All constants, paths, and env var loading.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("OPENROUTER_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))

# ── Model names ───────────────────────────────────────────────────────────────
# OpenRouter model ID — change this to any model available on openrouter.ai
CLAUDE_MODEL: str = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")
WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "medium")
WHISPER_FALLBACK_MODEL: str = "base"
WHISPER_TIMEOUT_SECONDS: int = 20 * 60  # 20 minutes

# ── Directory / file paths ────────────────────────────────────────────────────
# Resolve everything relative to the project root (two levels above this file)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / os.getenv("DATA_DIR", "data")

LECTURE_VIDEO: Path = DATA_DIR / "lecture.mp4"
TRANSCRIPT_TXT: Path = DATA_DIR / "transcript.txt"
SLIDES_PDF: Path = DATA_DIR / "slides.pdf"
GUIDELINES_TXT: Path = DATA_DIR / "guidelines.txt"

TIMESTAMPED_TRANSCRIPT: Path = DATA_DIR / "timestamped_transcript.json"
TOPIC_SEGMENTS: Path = DATA_DIR / "topic_segments.json"
FRAME_MANIFEST: Path = DATA_DIR / "frame_manifest.json"

FRAMES_DIR: Path = DATA_DIR / "frames"
SLIDES_IMAGES_DIR: Path = DATA_DIR / "slides_images"
CHROMA_PERSIST_DIR: Path = PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "data/chroma_db")
STUDENTS_DB: Path = DATA_DIR / "students.db"
AUDIO_WAV: Path = DATA_DIR / "audio.wav"

# ── ChromaDB ──────────────────────────────────────────────────────────────────
CHROMA_COLLECTION_NAME: str = "lecture_segments"
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
TOP_K_RESULTS: int = 4

# ── Segmentation ──────────────────────────────────────────────────────────────
SEGMENTATION_WINDOW_SECONDS: int = 20 * 60   # 20 min windows
SEGMENTATION_OVERLAP_SECONDS: int = 2 * 60   # 2 min overlap
MAX_TOKENS_PER_WINDOW: int = 6000

# ── Ensure output dirs exist ──────────────────────────────────────────────────
FRAMES_DIR.mkdir(parents=True, exist_ok=True)
SLIDES_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
