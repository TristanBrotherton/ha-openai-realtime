"""Per-session cost estimation and a daily budget guard.

Cost is computed from pipecat's LLM usage metrics (OpenAI's per-response
``response.done`` usage events). The estimate is a deliberate UPPER BOUND:
pipecat 0.0.97 doesn't expose the text/audio token split, so all non-cached
input tokens are priced at the model's audio-input rate and all output tokens
at its audio-output rate — audio dominates a voice session, so the estimate
runs at most a few percent high, never low. Web searches are counted at a
flat per-call estimate.

The daily ledger persists to /data (the add-on's persistent storage) so a
restart doesn't reset the budget. When ``daily_budget_usd`` is set (> 0) and
the day's estimated spend reaches it, new device connections are refused
until local midnight; an in-flight conversation is never cut mid-turn.
"""
import json
import logging
import os
import tempfile
from datetime import date

from pipecat.frames.frames import Frame, MetricsFrame
from pipecat.metrics.metrics import LLMUsageMetricsData
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection

logger = logging.getLogger(__name__)

# $ per 1M tokens: (audio_in, cached_in, audio_out). Upper-bound rates from
# https://developers.openai.com/api/docs/pricing (2026-06).
MODEL_RATES = {
    "gpt-realtime-2": (32.0, 0.40, 64.0),
    "gpt-realtime-1.5": (32.0, 0.40, 64.0),
    "gpt-realtime": (32.0, 0.40, 64.0),
    "gpt-realtime-mini": (10.0, 0.30, 20.0),
}
DEFAULT_RATES = (32.0, 0.40, 64.0)

# Flat upper-bound estimate per web_search call (a separate Responses API
# request, typically 1-3¢ depending on the search model).
WEB_SEARCH_EST_USD = 0.03


class UsageLedger:
    """Daily usage accounting, persisted across add-on restarts."""

    def __init__(self, model: str, daily_budget_usd: float = 0.0,
                 path: str = "/data/usage_ledger.json"):
        self.rates = MODEL_RATES.get(model, DEFAULT_RATES)
        self.daily_budget_usd = max(0.0, daily_budget_usd)
        self.path = path
        self._data = {"date": date.today().isoformat(), "spent_usd": 0.0,
                      "responses": 0, "web_searches": 0, "sessions": 0}
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                stored = json.load(f)
            if stored.get("date") == date.today().isoformat():
                self._data = stored
        except (OSError, ValueError):
            pass

    def _save(self):
        try:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".")
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f)
            os.replace(tmp, self.path)
        except OSError as e:
            logger.warning(f"⚠️ Could not persist usage ledger: {e!r}")

    def _roll_day(self):
        today = date.today().isoformat()
        if self._data["date"] != today:
            logger.info(f"📅 Usage ledger rolled over (yesterday: "
                        f"${self._data['spent_usd']:.2f}, {self._data['sessions']} sessions)")
            self._data = {"date": today, "spent_usd": 0.0, "responses": 0,
                          "web_searches": 0, "sessions": 0}
            self._save()

    @property
    def spent_usd(self) -> float:
        self._roll_day()
        return self._data["spent_usd"]

    def add_response(self, prompt_tokens: int, completion_tokens: int,
                     cached_tokens: int = 0) -> float:
        self._roll_day()
        audio_in, cached_in, audio_out = self.rates
        fresh = max(0, prompt_tokens - cached_tokens)
        cost = (fresh * audio_in + cached_tokens * cached_in
                + completion_tokens * audio_out) / 1_000_000
        self._data["spent_usd"] += cost
        self._data["responses"] += 1
        self._save()
        return cost

    def add_web_search(self):
        self._roll_day()
        self._data["spent_usd"] += WEB_SEARCH_EST_USD
        self._data["web_searches"] += 1
        self._save()

    def add_session(self):
        self._roll_day()
        self._data["sessions"] += 1
        self._save()
        logger.info(f"💰 Session #{self._data['sessions']} today | spent ≈ "
                    f"${self._data['spent_usd']:.3f}"
                    + (f" of ${self.daily_budget_usd:.2f} budget"
                       if self.daily_budget_usd else " (no budget cap)"))

    def over_budget(self) -> bool:
        self._roll_day()
        return (self.daily_budget_usd > 0
                and self._data["spent_usd"] >= self.daily_budget_usd)


class CostGuard(FrameProcessor):
    """Pipeline tap that prices every OpenAI response as it completes."""

    def __init__(self, ledger: UsageLedger, **kwargs):
        super().__init__(**kwargs)
        self._ledger = ledger

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, MetricsFrame):
            for item in frame.data:
                if isinstance(item, LLMUsageMetricsData):
                    usage = item.value
                    cost = self._ledger.add_response(
                        usage.prompt_tokens,
                        usage.completion_tokens,
                        usage.cache_read_input_tokens or 0,
                    )
                    logger.info(
                        f"💰 response ≈ ${cost:.4f} "
                        f"(in {usage.prompt_tokens} tok, out {usage.completion_tokens} tok, "
                        f"cached {usage.cache_read_input_tokens or 0}) | "
                        f"today ≈ ${self._ledger.spent_usd:.3f}")
                    if self._ledger.over_budget():
                        logger.warning(
                            f"🚫 Daily budget (${self._ledger.daily_budget_usd:.2f}) reached — "
                            "new sessions will be refused until midnight")
        await self.push_frame(frame, direction)
