"""Build a voice-print centroid from enrollment audio.

Usage (inside the add-on container):
    python3 -m app.build_voiceprint <name> /share/voice-enrollment/<file>.wav [...]

Embeds each file in ~3 s chunks, averages, normalizes, writes
/share/voice-prints/<name>.json.
"""
import json
import os
import sys
import wave

import numpy as np

from . import voiceprint


def main():
    name = sys.argv[1].strip().lower()
    files = sys.argv[2:]
    vecs = []
    for path in files:
        with wave.open(path) as f:
            assert f.getframerate() == 16000, path
            pcm = f.readframes(f.getnframes())
        step = 16000 * 2 * 3  # 3 s
        for i in range(0, max(1, len(pcm) - step), step):
            chunk = pcm[i:i + step]
            # skip near-silent chunks
            a = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            if np.sqrt(np.mean(a * a)) < 0.005:
                continue
            v = voiceprint.embed(chunk)
            if v is not None:
                vecs.append(v)
    if len(vecs) < 5:
        print(f"ERROR: only {len(vecs)} usable chunks — need more audio")
        sys.exit(1)
    c = np.mean(vecs, axis=0)
    c = c / np.linalg.norm(c)
    os.makedirs(voiceprint.PRINTS_DIR, exist_ok=True)
    out = os.path.join(voiceprint.PRINTS_DIR, f"{name}.json")
    json.dump({"name": name, "embedding": c.tolist(), "chunks": len(vecs)}, open(out, "w"))
    print(f"wrote {out} from {len(vecs)} chunks")


if __name__ == "__main__":
    main()
