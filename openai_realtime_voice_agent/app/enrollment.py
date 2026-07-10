"""Voice enrollment: guided, on-device capture of a household member's voice.

Broader goal than wake words: one guided session per person yields (a) real
wake-phrase positives for microWakeWord retraining, and (b) natural-speech
audio suitable for voice-print (speaker-ID) enrollment later. The user starts
it by voice ("I want to teach you my voice"); the model calls the
voice_enrollment tool and then FOLLOWS THE SCRIPT the tool returns, keeping the
conversation loop alive turn by turn while this recorder dumps every inbound
mic frame to a WAV.

Files land in /share/voice-enrollment/<person>_<timestamp>.wav (16 kHz mono
PCM16). /share persists across add-on rebuilds and is reachable from the HA
host, from where recordings are pulled into the household's private sample
store. THESE ARE PERSONAL DATA: never commit them to a repo.
"""
import asyncio
import logging
import os
import re
import time
import wave
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from pipecat.services.llm_service import FunctionCallParams

logger = logging.getLogger(__name__)

ENROLL_DIR = "/share/voice-enrollment"


async def _set_wake_sound(on: bool) -> None:
    """Toggle the device's wake-chime switch during enrollment (best effort).

    The chime otherwise plays over the guidance every time a wake-phrase
    repetition re-wakes the device (observed live — made instructions
    inaudible). Entity id comes from the WAKE_SOUND_ENTITY option; empty = skip.
    """
    entity = os.environ.get("WAKE_SOUND_ENTITY", "").strip()
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not entity or not token:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"http://supervisor/core/api/services/switch/turn_{'on' if on else 'off'}",
                headers={"Authorization": f"Bearer {token}"},
                json={"entity_id": entity},
            )
            r.raise_for_status()
        logger.info(f"🔔 wake sound {'restored' if on else 'muted'} ({entity})")
    except Exception as e:
        logger.warning(f"⚠️ could not toggle wake sound {entity}: {e!r}")
SAMPLE_RATE = 16000
MAX_SESSION_SECONDS = 15 * 60  # hard stop so a forgotten session can't record forever


class EnrollmentRecorder:
    """Continuous mic-stream recorder, toggled by the voice_enrollment tool."""

    def __init__(self):
        self._wav: Optional[wave.Wave_write] = None
        self.person: Optional[str] = None
        self.path: Optional[str] = None
        self._started_at: float = 0.0

    @property
    def active(self) -> bool:
        return self._wav is not None

    def start(self, person: str) -> str:
        if self._wav is not None:
            self.stop()
        safe = re.sub(r"[^a-z0-9_]+", "", person.lower().replace(" ", "_")) or "unknown"
        os.makedirs(ENROLL_DIR, exist_ok=True)
        path = os.path.join(ENROLL_DIR, f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}.wav")
        w = wave.open(path, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        self._wav = w
        self.person = safe
        self.path = path
        self._started_at = time.monotonic()
        logger.info(f"🎓 voice enrollment started for '{safe}' → {path}")
        return path

    def feed(self, pcm: bytes) -> None:
        if self._wav is None:
            return
        if time.monotonic() - self._started_at > MAX_SESSION_SECONDS:
            logger.warning("🎓 enrollment hit the 15-minute safety cap — stopping")
            self.stop()
            return
        try:
            self._wav.writeframes(pcm)
        except Exception as e:
            logger.warning(f"⚠️ enrollment write failed, stopping: {e!r}")
            self.stop()

    def stop(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {"person": self.person, "path": self.path, "seconds": 0.0}
        w, self._wav = self._wav, None
        if w is not None:
            try:
                frames = w.getnframes()
                info["seconds"] = round(frames / SAMPLE_RATE, 1)
                w.close()
            except Exception as e:
                logger.warning(f"⚠️ enrollment close failed: {e!r}")
        if info["path"]:
            logger.info(
                f"🎓 voice enrollment stopped for '{info['person']}' — "
                f"{info['seconds']}s captured at {info['path']}"
            )
        self.person = None
        self.path = None
        return info


ENROLLMENT_SCRIPT = (
    "Recording is ON — everything the microphone hears is being captured. You are "
    "guiding {person} through voice training. This is a CALL-AND-RESPONSE drill and "
    "your discipline matters more than theirs: after EVERY utterance they make "
    "during the drill, you reply with EXACTLY ONE WORD — 'next' — nothing else, no "
    "commentary, no counting aloud, no encouragement, no 'I'm waiting'. The one "
    "exception: when it is time to switch style, use one SHORT phrase (five words "
    "or fewer) to announce it, then back to one-word replies. "
    "Open the session with this, briskly: the wake chime is off; each time you say "
    "'next', they say 'hey leonard' once; if the ring flashes red or it stops "
    "listening, that is harmless — say 'hey leonard' to silently re-wake and carry "
    "on. Then run the drill, counting their utterances silently: "
    "reps 1-8 normal; announce 'Now quickly.' then reps 9-13 fast and casual; "
    "announce 'Now lazily.' then reps 14-18 quiet or mumbled; announce 'From "
    "across the room now.' then reps 19-24 louder from a distance; announce 'Last "
    "one, any way you like.' for rep 25. "
    "If an utterance was garbled or empty, 'again' instead of 'next'. "
    "After rep 25, ask them to talk normally for about NINETY seconds — describe "
    "their day, read something, ramble; if they stop early say only 'go on'. "
    "When the ninety seconds are done, call voice_enrollment with action 'stop', "
    "and ONLY AFTER the tool confirms, thank them briefly and suggest — once, "
    "lightly — a second session in another room. If the session drops they can "
    "wake you and say 'continue voice training' — start a fresh session; all takes "
    "count. Never chat, never explain the technology."
)


def get_enrollment_tool_definition() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "voice_enrollment",
        "description": (
            "Start or stop a guided voice-training (enrollment) recording session "
            "for a household member. Use when someone asks to train, teach, or "
            "enroll their voice (e.g. 'teach the assistant my voice', 'voice "
            "training', 'continue voice training'). Call start IMMEDIATELY and "
            "WITHOUT a person name — the system identifies the speaker by voice "
            "automatically (never ask who is enrolling unless the tool says it "
            "could not identify them, or they are enrolling someone else). Then "
            "follow the returned protocol exactly. Recording captures everything "
            "the microphone hears until stopped."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "status"],
                    "description": "start a session, stop the current one, or check status",
                },
                "person": {
                    "type": "string",
                    "description": (
                        "First name of the person enrolling. OPTIONAL: leave it out "
                        "and the system uses the voice-identified speaker "
                        "automatically. Only provide it when enrolling someone "
                        "other than the current speaker."
                    ),
                },
            },
            "required": ["action"],
        },
    }


def create_enrollment_tool_handler(
    recorder: EnrollmentRecorder,
    get_speaker_name: Optional[Callable[[], Optional[str]]] = None,
) -> Callable[["FunctionCallParams"], Awaitable[None]]:
    async def enrollment_tool_handler(params: "FunctionCallParams") -> None:
        args = params.arguments or {}
        action = (args.get("action") or "").strip().lower()
        person = (args.get("person") or "").strip()
        try:
            if action == "start":
                if not person and get_speaker_name is not None:
                    # The voice verdict races the model's first tool call (the
                    # probe needs ~3 s of mic audio). Wait for it briefly rather
                    # than making the user answer a question the VAD tends to
                    # drop (one-word replies often never commit — observed live).
                    for _ in range(12):  # up to ~6 s
                        person = (get_speaker_name() or "").strip()
                        if person:
                            break
                        await asyncio.sleep(0.5)
                if not person:
                    await params.result_callback(
                        {"error": (
                            "Could not identify the speaker by voice. Ask for their "
                            "first name, then call start again with person set — and "
                            "tell them to answer promptly."
                        )}
                    )
                    return
                recorder.start(person)
                await _set_wake_sound(False)
                await params.result_callback(
                    {"status": "recording", "instructions": ENROLLMENT_SCRIPT.format(person=person)}
                )
            elif action == "stop":
                info = recorder.stop()
                await _set_wake_sound(True)
                if not info.get("path"):
                    await params.result_callback({"status": "no active enrollment session"})
                else:
                    await params.result_callback(
                        {
                            "status": "saved",
                            "person": info["person"],
                            "seconds_recorded": info["seconds"],
                            "note": "Recording is off. Thank them briefly; the household admin will process the file.",
                        }
                    )
            elif action == "status":
                await params.result_callback(
                    {"recording": recorder.active, "person": recorder.person}
                )
            else:
                await params.result_callback({"error": f"unknown action '{action}'"})
        except Exception as e:
            logger.error(f"❌ voice_enrollment failed: {e}", exc_info=True)
            try:
                recorder.stop()
                await _set_wake_sound(True)
            except Exception:
                pass
            await params.result_callback(
                {"error": "Enrollment hit a technical problem; recording is off. Apologize briefly."}
            )

    return enrollment_tool_handler
