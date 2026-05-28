"""Emit va_client phase messages from Pipecat speaking frames.

The Home Assistant Voice PE firmware (maxmaxme `va_client` component) drives its
LED ring, mic-streaming gate and a 7 s no-speech watchdog from `phase` JSON
messages sent by the backend:

    {"type": "phase", "value": "listening" | "thinking" | "replying" | "idle"}

Without these messages the device aborts each turn after the watchdog fires, so
emitting them is required (not just cosmetic). This processor maps Pipecat's
standard speaking frames onto those phases and forwards them to the device over
the websocket as TEXT frames.

Mapping (matches the maxmaxme protocol / its CLAUDE.md):
    UserStartedSpeakingFrame  -> listening   (server VAD heard the user)
    UserStoppedSpeakingFrame  -> thinking    (generating a response)
    BotStartedSpeakingFrame   -> replying    (TTS audio is playing)
    BotStoppedSpeakingFrame   -> idle        (turn finished)

A barge-in mid-reply surfaces as a fresh UserStartedSpeakingFrame -> "listening"
while audio is still queued; the firmware uses that to flush playback.
"""
import logging

from pipecat.frames.frames import (
    Frame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection

logger = logging.getLogger(__name__)


class PhaseEmitter(FrameProcessor):
    """Forwards phase transitions to the device as JSON text frames."""

    def __init__(self, send_phase, **kwargs):
        """
        Args:
            send_phase: async callable(value: str) that delivers the phase to
                the connected device(s).
        """
        super().__init__(**kwargs)
        self._send_phase = send_phase

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        value = None
        if isinstance(frame, UserStartedSpeakingFrame):
            value = "listening"
        elif isinstance(frame, UserStoppedSpeakingFrame):
            value = "thinking"
        elif isinstance(frame, BotStartedSpeakingFrame):
            value = "replying"
        elif isinstance(frame, BotStoppedSpeakingFrame):
            value = "idle"

        if value is not None and self._send_phase is not None:
            try:
                await self._send_phase(value)
            except Exception as e:  # never let UI signalling break the audio path
                logger.warning(f"⚠️ Failed to emit phase '{value}': {e}")

        await self.push_frame(frame, direction)
