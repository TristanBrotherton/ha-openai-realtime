"""Voice-print speaker identification (upgrade over the pitch heuristic).

Embeds a wake's capture audio with a sherpa-onnx speaker-embedding model and
compares against per-person centroids enrolled from the household's voice
recordings. Falls back cleanly: no model file or no centroids -> the caller
keeps using the pitch heuristic.

Centroids live in /share/voice-prints/<name>.json ({"name","embedding":[...]})
— built by embedding enrollment audio (see enroll_centroid()). Thresholds per
wyoming-voice-match field data: enrolled speakers score ~0.35-0.7 cosine,
strangers ~0.05-0.25.
"""
import json
import logging
import os
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = os.environ.get("VOICEPRINT_MODEL", "/opt/voiceprint/embedder.onnx")
PRINTS_DIR = "/share/voice-prints"
MATCH_THRESHOLD = 0.40      # >= : that person
UNCERTAIN_THRESHOLD = 0.28  # between: uncertain; below: unknown (guest)
SAMPLE_RATE = 16000

_extractor = None
_prints: Optional[dict] = None


def _load_extractor():
    global _extractor
    if _extractor is not None:
        return _extractor
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        import sherpa_onnx
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL_PATH, num_threads=2)
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
        logger.info(f"🧬 voice-print embedder loaded ({MODEL_PATH})")
    except Exception as e:
        logger.warning(f"⚠️ voice-print embedder unavailable: {e!r}")
        _extractor = None
    return _extractor


def _load_prints() -> dict:
    global _prints
    if _prints is not None:
        return _prints
    out = {}
    try:
        for f in os.listdir(PRINTS_DIR):
            if f.endswith(".json"):
                d = json.load(open(os.path.join(PRINTS_DIR, f)))
                out[d["name"]] = np.array(d["embedding"], dtype=np.float32)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"⚠️ voice-print load failed: {e!r}")
    _prints = out
    if out:
        logger.info(f"🧬 voice prints loaded: {sorted(out)}")
    return out


def available() -> bool:
    return _load_extractor() is not None and bool(_load_prints())


def embed(pcm16: bytes) -> Optional[np.ndarray]:
    ex = _load_extractor()
    if ex is None:
        return None
    audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    s = ex.create_stream()
    s.accept_waveform(SAMPLE_RATE, audio)
    s.input_finished()
    if not ex.is_ready(s):
        return None
    v = np.array(ex.compute(s), dtype=np.float32)
    n = np.linalg.norm(v)
    return v / n if n > 0 else None


def identify(pcm16: bytes) -> Tuple[str, Optional[str], float]:
    """Returns (level, name, score): level in {match, uncertain, unknown, unavailable}."""
    prints = _load_prints()
    v = embed(pcm16)
    if v is None or not prints:
        return "unavailable", None, 0.0
    best_name, best = None, -1.0
    for name, c in prints.items():
        score = float(np.dot(v, c))
        if score > best:
            best_name, best = name, score
    if best >= MATCH_THRESHOLD:
        return "match", best_name, best
    if best >= UNCERTAIN_THRESHOLD:
        return "uncertain", best_name, best
    return "unknown", None, best
