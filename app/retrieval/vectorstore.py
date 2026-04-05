"""
vectorstore.py - ChromaDB setup, ingestion, and query.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_collection = None  # module-level cache


def _get_collection():
    """Return (and lazily initialise) the ChromaDB collection."""
    global _collection
    if _collection is not None:
        return _collection

    from app.config import (
        CHROMA_COLLECTION_NAME,
        CHROMA_PERSIST_DIR,
        EMBEDDING_MODEL,
    )

    import chromadb  # type: ignore
    from chromadb.utils import embedding_functions  # type: ignore

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

    client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    _collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info(
        "ChromaDB collection '%s' ready (%d docs)",
        CHROMA_COLLECTION_NAME,
        _collection.count(),
    )
    return _collection


def _get_transcript_text(
    topic_seg: dict,
    timestamped_segments: list,
) -> str:
    """
    Extract raw transcript text for the time range of this topic segment.
    Falls back to summary if no match.
    """
    start = topic_seg.get("start_time", 0)
    end = topic_seg.get("end_time", start + 60)
    texts = [
        s["text"] for s in timestamped_segments
        if start <= s.get("start", 0) <= end
    ]
    if texts:
        return " ".join(texts)
    return topic_seg.get("summary", "")


def ingest_data(
    topic_segments: list,
    frame_manifest: list,
    slide_records: list,
    timestamped_segments: list,
) -> None:
    """
    Ingest all processed data into ChromaDB.
    Skips segments that are already indexed (idempotent).
    """
    if not topic_segments:
        logger.warning("No topic segments to ingest.")
        return

    collection = _get_collection()

    # Build frame index: segment_id -> list of filenames
    frame_index: dict = {}
    for frame in frame_manifest:
        sid = frame.get("segment_id", "")
        frame_index.setdefault(sid, []).append(frame["filename"])

    # Build slide descriptions list
    slide_text_chunks = []
    for slide in slide_records:
        slide_text_chunks.append(slide.get("description", f"Slide {slide['page_num']}"))

    existing_ids = set(collection.get()["ids"])

    ids, documents, metadatas = [], [], []

    for seg in topic_segments:
        seg_id = seg.get("segment_id", f"seg_{len(ids):03d}")
        if seg_id in existing_ids:
            continue

        doc_text = _get_transcript_text(seg, timestamped_segments)
        # Augment with summary and key concepts for better retrieval
        key_concepts = seg.get("key_concepts", [])
        if isinstance(key_concepts, list):
            key_concepts_str = ", ".join(key_concepts)
        else:
            key_concepts_str = str(key_concepts)

        full_doc = (
            f"TOPIC: {seg.get('title', '')}\n"
            f"SUMMARY: {seg.get('summary', '')}\n"
            f"KEY CONCEPTS: {key_concepts_str}\n"
            f"TRANSCRIPT: {doc_text}"
        )

        keyframes = frame_index.get(seg_id, [])

        metadata = {
            "topic_title": seg.get("title", ""),
            "summary": seg.get("summary", ""),
            "start_time": float(seg.get("start_time", 0)),
            "end_time": float(seg.get("end_time", 0)),
            "key_concepts": key_concepts_str,
            "lecture_num": 1,
            "keyframe_paths": ",".join(keyframes),
            "has_diagram": bool(seg.get("has_visual_reference", False)),
            "slide_paths": "",  # linked by concept matching below
        }

        ids.append(seg_id)
        documents.append(full_doc)
        metadatas.append(metadata)

    if ids:
        # ChromaDB upsert in batches of 100
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            collection.add(
                ids=ids[i : i + batch_size],
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
            )
        logger.info("Ingested %d segments into ChromaDB", len(ids))
    else:
        logger.info("All segments already indexed, nothing to add.")


def query(question: str, top_k: int = 4) -> list:
    """
    Semantic search in ChromaDB.

    Returns list of result dicts with keys: id, document, metadata, distance.
    """
    from app.config import TOP_K_RESULTS
    k = top_k or TOP_K_RESULTS

    collection = _get_collection()
    if collection.count() == 0:
        logger.warning("ChromaDB collection is empty. Run the processing pipeline first.")
        return []

    results = collection.query(
        query_texts=[question],
        n_results=min(k, collection.count()),
    )

    output = []
    for i, doc_id in enumerate(results["ids"][0]):
        output.append({
            "id": doc_id,
            "document": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i] if results.get("distances") else None,
        })
    return output


def reset_collection() -> None:
    """Drop and recreate the collection (useful for re-processing)."""
    global _collection
    from app.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, EMBEDDING_MODEL
    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    try:
        client.delete_collection(CHROMA_COLLECTION_NAME)
        logger.info("Deleted collection '%s'", CHROMA_COLLECTION_NAME)
    except Exception:
        pass
    _collection = None
