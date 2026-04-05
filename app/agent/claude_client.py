"""
claude_client.py - LLM API integration via OpenRouter (OpenAI-compatible).
Supports optional vision input via frame_base64.
"""

import logging
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def call_claude(
    system_prompt: str,
    user_message: str,
    api_key: str,
    model: str,
    max_tokens: int = 2048,
    frame_base64: Optional[str] = None,
) -> str:
    """
    Send a system + user message via OpenRouter and return the response text.
    If frame_base64 is provided, attaches the image as a vision input.
    """
    client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)

    if frame_base64:
        user_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{frame_base64}",
                },
            },
            {
                "type": "text",
                "text": user_message,
            },
        ]
    else:
        user_content = user_message

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )

    text = response.choices[0].message.content
    logger.debug("LLM response (%d chars): %s…", len(text), text[:120])
    return text
