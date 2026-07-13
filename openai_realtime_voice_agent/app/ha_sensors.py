"""Publish live Voice PE state to Home Assistant as sensors.

Per-instance sensors (INSTANCE_NAME option, e.g. 'kitchen'):
  sensor.voicepe_<inst>_speaker        james/mary/unknown/none (+score/method)
  sensor.voicepe_<inst>_active_timers  count (+next-expiry attrs)
  binary_sensor.voicepe_<inst>_enrollment_active
  sensor.voicepe_<inst>_wakes_today / _false_wakes_today

States are POSTed via the supervisor core API — ad-hoc entities, ideal for
dashboards and automations (e.g. per-person scenes on speaker change).
"""
import logging
import os
import time
from datetime import date

import httpx

logger = logging.getLogger(__name__)

_INST = os.environ.get("INSTANCE_NAME", "").strip().lower() or "device"
_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")


async def _post(entity: str, state, attrs: dict) -> None:
    if not _TOKEN:
        return
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post(
                f"http://supervisor/core/api/states/{entity}",
                headers={"Authorization": f"Bearer {_TOKEN}"},
                json={"state": str(state), "attributes": attrs},
            )
            r.raise_for_status()
    except Exception as e:
        logger.debug(f"sensor post failed ({entity}): {e!r}")


class SensorPublisher:
    def __init__(self):
        self._day = date.today().isoformat()
        self._wakes = 0
        self._false = 0

    def _roll(self):
        d = date.today().isoformat()
        if d != self._day:
            self._day, self._wakes, self._false = d, 0, 0

    async def speaker(self, label: str, name, score: float, method: str):
        state = name or ("unknown" if label == "unknown" else "none")
        await _post(f"sensor.voicepe_{_INST}_speaker", state, {
            "friendly_name": f"Voice PE {_INST} speaker",
            "label": label, "score": round(float(score), 3), "method": method,
            "at": time.strftime("%H:%M:%S"),
        })

    async def usage(self, cost: float, detail: dict):
        """Accumulate estimated OpenAI spend and publish it as a sensor."""
        self._roll()
        self._cost_today = getattr(self, "_cost_today", 0.0)
        self._responses_today = getattr(self, "_responses_today", 0)
        if getattr(self, "_cost_day", self._day) != self._day:
            self._cost_today, self._responses_today = 0.0, 0
        self._cost_day = self._day
        self._cost_today += cost
        self._responses_today += 1
        await _post(f"sensor.voicepe_{_INST}_openai_cost_today", round(self._cost_today, 4), {
            "friendly_name": f"Voice PE {_INST} OpenAI cost today",
            "unit_of_measurement": "$", "responses_today": self._responses_today,
            "last_response_cost": round(cost, 5), **detail,
        })

    async def voice_prints(self):
        """Publish enrolled voice prints so users can SEE enrollment worked."""
        import glob, json as _json
        names = []
        for f in sorted(glob.glob("/share/voice-prints/*.json")):
            try:
                d = _json.load(open(f))
                names.append({"name": d.get("name") or os.path.basename(f)[:-5],
                              "chunks": d.get("chunks", 0)})
            except Exception:
                continue
        configured = [n for n in (os.environ.get("SPEAKER_MALE_NAME", ""),
                                  os.environ.get("SPEAKER_FEMALE_NAME", "")) if n.strip()]
        await _post(f"sensor.voicepe_{_INST}_voice_prints", len(names), {
            "friendly_name": f"Voice PE {_INST} enrolled voice prints",
            "enrolled": [n["name"] for n in names],
            "chunks": {n["name"]: n["chunks"] for n in names},
            "configured_names": configured,
            "active": [n["name"] for n in names
                       if n["name"].lower() in {c.strip().lower() for c in configured}],
        })

    async def wake(self):
        self._roll(); self._wakes += 1
        await _post(f"sensor.voicepe_{_INST}_wakes_today", self._wakes,
                    {"friendly_name": f"Voice PE {_INST} wakes today"})

    async def false_wake(self):
        self._roll(); self._false += 1
        await _post(f"sensor.voicepe_{_INST}_false_wakes_today", self._false,
                    {"friendly_name": f"Voice PE {_INST} false wakes today"})

    async def timers(self, registry):
        t = registry.list_timers()["timers"]
        attrs = {"friendly_name": f"Voice PE {_INST} active timers"}
        if t:
            attrs["next_label"] = t[0]["label"]
            attrs["next_seconds_left"] = min(x["seconds_left"] for x in t)
        await _post(f"sensor.voicepe_{_INST}_active_timers", len(t), attrs)

    async def enrollment(self, active: bool):
        await _post(f"binary_sensor.voicepe_{_INST}_enrollment_active",
                    "on" if active else "off",
                    {"friendly_name": f"Voice PE {_INST} enrollment active"})


PUBLISHER = SensorPublisher()
