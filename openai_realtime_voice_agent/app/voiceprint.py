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


MIN_IDENTIFY_SECONDS = 2.5  # of VOICED audio (silence is stripped first)


def _voiced_only(pcm16: bytes) -> bytes:
    """Strip silence: live wake captures are mostly dead air, and silence
    dilutes embeddings into confident garbage (observed live: a valid speaker
    at 0.11 because 3 s of buffer held 0.85 s of speech)."""
    a = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    hop = SAMPLE_RATE // 20
    n = len(a) // hop
    if n < 2:
        return pcm16
    rms = np.array([np.sqrt(np.mean(a[i*hop:(i+1)*hop]**2)) for i in range(n)])
    gate = max(rms.max() * 0.08, 1e-4)
    idx = rms > gate
    if not idx.any():
        return b""
    keep = np.concatenate([a[i*hop:(i+1)*hop] for i in range(n) if idx[i]])
    return (keep * 32768).astype(np.int16).tobytes()


def identify(pcm16: bytes) -> Tuple[str, Optional[str], float]:
    """Returns (level, name, score): level in {match, uncertain, unknown, unavailable}."""
    voiced = _voiced_only(pcm16)
    # Guard on VOICED duration — below it, defer to the pitch fallback rather
    # than embed unreliable audio (validated: short-clip embeddings are noisy).
    if len(voiced) < int(MIN_IDENTIFY_SECONDS * SAMPLE_RATE * 2):
        return "unavailable", None, 0.0
    pcm16 = voiced
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
