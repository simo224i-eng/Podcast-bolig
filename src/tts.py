"""Text-to-speech via edge-tts. No API key, free."""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import edge_tts

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "da-DK-JeppeNeural"
ALT_VOICE = "da-DK-ChristelNeural"
# edge-tts breaks above ~10k chars per request; keep generous safety margin.
MAX_CHUNK_CHARS = 3000


def _split_into_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text into <= max_chars chunks at sentence/paragraph boundaries."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # Prefer paragraph breaks, fall back to sentence breaks
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:
            # Split this paragraph by sentences
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                if len(buf) + len(sent) + 1 > max_chars and buf:
                    chunks.append(buf.strip())
                    buf = ""
                if len(sent) > max_chars:
                    # Hard split — rare, but be safe
                    for i in range(0, len(sent), max_chars):
                        piece = sent[i : i + max_chars]
                        if buf:
                            chunks.append(buf.strip())
                            buf = ""
                        chunks.append(piece)
                else:
                    buf = f"{buf} {sent}".strip()
        else:
            if len(buf) + len(para) + 2 > max_chars and buf:
                chunks.append(buf.strip())
                buf = ""
            buf = f"{buf}\n\n{para}".strip()
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


async def _synthesize_chunk(
    text: str, voice: str, out_file, rate: str = "+0%"
) -> None:
    """Synthesize one chunk and append the audio bytes to an open file."""
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    async for event in communicate.stream():
        if event["type"] == "audio":
            out_file.write(event["data"])


async def synthesize(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
) -> Path:
    """Synthesize `text` to an mp3 file at `output_path`.

    Long texts are split into chunks and concatenated as a single mp3.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    chunks = _split_into_chunks(text)
    logger.info(
        "Synthesizing %d chunks (%d chars total) to %s",
        len(chunks),
        sum(len(c) for c in chunks),
        output_path.name,
    )
    with output_path.open("wb") as f:
        for i, chunk in enumerate(chunks, 1):
            logger.debug("Chunk %d/%d (%d chars)", i, len(chunks), len(chunk))
            await _synthesize_chunk(chunk, voice, f, rate=rate)
    return output_path


def synthesize_sync(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
) -> Path:
    """Sync wrapper around `synthesize`."""
    return asyncio.run(synthesize(text, output_path, voice=voice, rate=rate))
