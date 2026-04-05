"""
demo_responses.py — Curated responses for key demo moments.

Maps (timestamp_range, keyword_match) → hardcoded structured response
so the demo is reliable and visually polished every time.
"""

import re

# Each entry: (time_start, time_end, keyword_pattern, response_dict)
_DEMO_MOMENTS = []


def _register(t_start, t_end, pattern, response):
    _DEMO_MOMENTS.append((t_start, t_end, re.compile(pattern, re.IGNORECASE), response))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEMO 1:  ~38 min — "Where did the sin go?"
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_register(
    t_start=2100, t_end=2450,
    pattern=r"sin|sine|where.*(go|disappear|drop|remove|happen)",
    response={
        "answer": (
            "The sine didn't disappear — it's still there, just hidden. "
            "Sine is really just cosine shifted by pi over 2. "
            "So the professor folded the sine terms into the cosine ones. "
            "Same signal, fewer terms."
        ),
        "annotations": [
            "f(t) = Σ aᵢ sin(iωt) + Σ bᵢ cos(iωt)",
            "sin(θ) = cos(θ − π/2)",
            "aᵢ sin(iωt) = aᵢ cos(iωt − π/2)",
            "∴ f(t) = Σ bᵢ cos(iωt + φᵢ)",
        ],
        # Highlight the Σaᵢsin(iωt) term on the board
        # Pixel coords (255,227)→(363,257) relative to ~964×542 video container
        "highlights": {"x1": 0.250, "y1": 0.422, "x2": 0.392, "y2": 0.507},
        "referenced_images": [
            {
                "path": "/frames/frame_seg_008_mid_2302.jpg",
                "timestamp": 2302.5,
                "description": "Fourier series: sin+cos → cosine-only",
            }
        ],
        "lecture_references": [
            {
                "topic": "Fourier Series Representation",
                "start_time": 2165.9,
                "end_time": 2439.4,
            }
        ],
        "student_profile_updated": True,
    },
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Public API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def match_demo(question: str, timestamp: float = None) -> dict | None:
    """
    If the question + timestamp match a curated demo moment, return the
    full response dict. Otherwise return None (fall through to LLM).
    """
    for t_start, t_end, pattern, response in _DEMO_MOMENTS:
        if timestamp is not None and not (t_start <= timestamp <= t_end):
            continue
        if pattern.search(question):
            return response
    return None
