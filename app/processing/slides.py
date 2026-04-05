"""
slides.py - PDF slide processing.

Converts each slide page to a PNG, optionally describes it via Claude Vision,
and returns a list of slide dicts for ChromaDB ingestion.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_SLIDES_MANIFEST = "slides_manifest.json"


def _describe_slide(
    image_path: Path,
    page_num: int,
    client: OpenAI,
    model: str,
) -> str:
    """Ask the vision model to describe a slide image."""
    import base64
    try:
        data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
        response = client.chat.completions.create(
            model=model,
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{data}",
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f"This is slide {page_num} from a CSCI 576 (Multimedia Systems) "
                                "lecture. Extract all visible text from this slide and provide a "
                                "brief description of any diagrams or visual elements. "
                                "Format: first the extracted text, then a short description."
                            ),
                        },
                    ],
                }
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("Slide description failed for page %d: %s", page_num, exc)
        return f"Slide {page_num}"


def run_slide_processing(
    pdf_path: Path,
    slides_dir: Path,
    api_key: str,
    model: str,
    describe: bool = True,
) -> list:
    """
    Main entry point.

    Converts PDF pages to PNGs, optionally describes them,
    returns list of slide dicts.
    """
    manifest_path = slides_dir / _SLIDES_MANIFEST

    if manifest_path.exists():
        logger.info("Slides manifest already exists, loading.")
        with open(manifest_path) as f:
            return json.load(f)

    if not pdf_path.exists():
        logger.warning("slides.pdf not found at %s, skipping slide processing.", pdf_path)
        return []

    try:
        from pdf2image import convert_from_path  # type: ignore
    except ImportError:
        logger.error("pdf2image is not installed. Skipping slide processing.")
        return []

    logger.info("Converting PDF slides to images…")
    try:
        images = convert_from_path(str(pdf_path), dpi=150)
    except Exception as exc:
        logger.error("PDF conversion failed: %s", exc)
        return []

    client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL) if (describe and api_key) else None
    slide_records: list = []

    for page_num, img in enumerate(images, start=1):
        filename = f"slide_{page_num:03d}.png"
        out_path = slides_dir / filename

        if not out_path.exists():
            img.save(str(out_path), "PNG")
            logger.info("Saved %s", filename)

        description = ""
        if client and out_path.exists():
            description = _describe_slide(out_path, page_num, client, model)

        slide_records.append({
            "filename": filename,
            "page_num": page_num,
            "description": description,
        })

    logger.info("Processed %d slides", len(slide_records))

    with open(manifest_path, "w") as f:
        json.dump(slide_records, f, indent=2)

    return slide_records
