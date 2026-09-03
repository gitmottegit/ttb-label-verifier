"""Label reading via the Claude vision API.

The model is used strictly as a resilient OCR/layout reader — it transcribes
what is on the label (including awkward angles, glare, or odd fonts) into a
structured record. It makes no compliance decisions; those happen in
`verification.py`. A forced tool call guarantees we always get valid JSON back.
"""

from __future__ import annotations

import base64
import io
import logging
import os

import anthropic
from PIL import Image, ImageOps

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Anthropic vision performs best with the long side at or under ~1568 px;
# downscaling oversized uploads also keeps latency inside our 5-second budget.
MAX_DIMENSION = 1568

_client: anthropic.AsyncAnthropic | None = None


class ExtractionError(Exception):
    """Raised when the label image cannot be read."""


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ExtractionError(
                "Server is missing its ANTHROPIC_API_KEY — see README setup steps.")
        _client = anthropic.AsyncAnthropic()
    return _client


EXTRACTION_TOOL = {
    "name": "record_label_fields",
    "description": "Record the fields transcribed from an alcohol beverage label image.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand_name": {"type": ["string", "null"], "description": "Brand name exactly as printed, preserving capitalization."},
            "class_type": {"type": ["string", "null"], "description": "Class/type designation exactly as printed (e.g. 'Kentucky Straight Bourbon Whiskey')."},
            "alcohol_content": {"type": ["string", "null"], "description": "Alcohol content statement exactly as printed, e.g. '45% Alc./Vol. (90 Proof)'."},
            "net_contents": {"type": ["string", "null"], "description": "Net contents exactly as printed, e.g. '750 mL'."},
            "bottler_name_address": {"type": ["string", "null"], "description": "Name and address of the bottler/producer/importer if printed."},
            "country_of_origin": {"type": ["string", "null"], "description": "Country of origin statement if printed."},
            "government_warning_verbatim": {"type": ["string", "null"], "description": "The full government warning statement transcribed verbatim, character for character, PRESERVING the exact capitalization printed on the label. Null if absent."},
            "warning_appears_bold": {"type": ["boolean", "null"], "description": "Whether the 'GOVERNMENT WARNING:' lead-in appears bold relative to surrounding text."},
            "readability_issues": {"type": "array", "items": {"type": "string"}, "description": "Any conditions that made the label hard to read (glare, angle, blur, low resolution, text partially cut off). Empty if the image is clean."},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"], "description": "Overall confidence in the transcription."},
        },
        "required": ["brand_name", "class_type", "alcohol_content", "net_contents",
                     "government_warning_verbatim", "readability_issues", "confidence"],
    },
}

SYSTEM_PROMPT = (
    "You transcribe alcohol beverage label images for a compliance workflow. "
    "Transcribe exactly what is printed — never correct, complete, or normalize "
    "text, and never fill in what a field 'should' say. Preserve capitalization "
    "character-for-character, especially in the government warning statement. "
    "If the photo is imperfect (angle, glare, blur), read it as best you can and "
    "list the problems in readability_issues. If a field is absent or truly "
    "illegible, record null rather than guessing."
)


def prepare_image(data: bytes) -> tuple[bytes, str]:
    """Validate, auto-orient, and downscale an uploaded image. Returns (bytes, media_type)."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ExtractionError("Image is larger than 8 MB. Please upload a smaller file.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ExtractionError("File is not a readable image (PNG, JPEG, or WebP).") from exc

    img = ImageOps.exif_transpose(img)
    if max(img.size) > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue(), "image/png"


async def extract_label_fields(image_bytes: bytes) -> dict:
    """Send one label image to Claude and return the structured transcription."""
    data, media_type = prepare_image(image_bytes)
    client = _get_client()
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "record_label_fields"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type,
                        "data": base64.standard_b64encode(data).decode(),
                    }},
                    {"type": "text", "text": "Transcribe this label."},
                ],
            }],
        )
    except anthropic.APIStatusError as exc:
        # Full detail to server logs; users get a plain-language message.
        logging.getLogger("uvicorn.error").error(
            "Anthropic API error %s: %s", exc.status_code, exc.response.text[:2000])
        raise ExtractionError(f"Label reading service error ({exc.status_code}). Please retry.") from exc
    except anthropic.APIConnectionError as exc:
        raise ExtractionError("Could not reach the label reading service. Please retry.") from exc

    for block in response.content:
        if block.type == "tool_use" and block.name == EXTRACTION_TOOL["name"]:
            return dict(block.input)
    raise ExtractionError("The label reader returned no result. Please retry.")
