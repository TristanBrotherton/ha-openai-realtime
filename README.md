# Voice PE Realtime — backend add-on

Turn a Home Assistant Voice PE into a natural speech-to-speech assistant powered
by the OpenAI Realtime API — with instant smart-home control, speaker awareness,
and on-device voice training. This is the **backend half**: a Home Assistant
add-on that owns the OpenAI session and your home's tools. It pairs with the
[Voice PE Realtime firmware](https://github.com/TristanBrotherton/voicepe-realtime-firmware),
which turns the device into a thin audio client.

## The experience

Say your wake word and just talk. Replies are generated speech-to-speech (no
STT→LLM→TTS chain), so tone and timing feel like conversation. Smart-home
actions run through Home Assistant's native tools and respond instantly —
lights, climate, media, shopping lists. A follow-up window keeps the mic open
after each reply so conversations flow without re-waking. Say "stop" mid-reply
and it stops.

- **It knows who's talking.** Configure two household names and each wake is
  voice-identified — the assistant can say "sir" or "ma'am", use names
  naturally, and restrict chosen tools to one speaker (enforced below the
  model, so it can't be talked around).
- **It learns your voices.** Say *"teach me my voice"*: the device pins its mic
  open (cyan breathing ring), an automated audio coach walks you through 25
  varied wake-word repetitions plus 90 seconds of natural speech, and the
  recording lands on your box — never sent to any cloud — ready for wake-word
  training or voice-print enrollment. Press the device button to stop anytime.
- **It learns from its mistakes.** Every wake's opening audio is archived
  locally (auto-pruned, newest 500). False trigger? Say *"that was a false
  alarm"* and it labels the capture for the next wake-word retrain.

## Features

- OpenAI Realtime speech-to-speech (`gpt-realtime-2.1` or any model id)
- Native Home Assistant control via the official MCP Server integration
- Speaker awareness + speaker-gated tools (`speaker_male_name`,
  `speaker_female_name`, `male_only_tools`)
- Guided voice enrollment (`enrollment_phrase`, `enrollment_tts_voice`),
  wake-chime auto-mute during sessions (`wake_sound_entity`)
- Failure harvesting: capture archive + `mark_false_wake` voice labeling
- Web search tool (secondary OpenAI call, configurable model)
- Persona fully yours via `instructions` (ours is a dry British butler)
- Production hardening: proactive session refresh before OpenAI's 60-minute
  cap, reconnect recovery, echo/ghost-turn guards, stop-word authority,
  turn-liveness watchdogs

## Install

1. Add this repository URL in **Settings → Add-ons → Add-on store → ⋮ →
   Repositories**, then install **OpenAI Realtime Voice Agent**.
2. Set your OpenAI API key. Install Home Assistant's **MCP Server** integration
   and expose your entities to Assist. Leave `ha_mcp_url` empty (it uses the
   built-in server).
3. Flash the paired
   [firmware](https://github.com/TristanBrotherton/voicepe-realtime-firmware)
   on your Voice PE, pointing its `va_url` at this add-on (`ws://<ha-ip>:8080/`).

**Multiple devices:** the backend serves one device per instance. Run one
add-on instance per Voice PE, each on its own `websocket_port`, each device's
`va_url` pointing at its port.

## Notable options

| Option | Purpose |
|---|---|
| `openai_model` / `openai_model_custom` | Realtime model (any model id via custom) |
| `openai_voice` | TTS voice (accent is steerable via `instructions`) |
| `follow_up_listen_seconds` | Mic-open window after replies (default 8) |
| `wake_open_delay_ms` / `follow_up_open_delay_ms` | Echo guards; lower = snappier, riskier |
| `playback_prebuffer_ms` | Raise (~250) if you hear start-of-reply crackle |
| `noise_reduction` | Usually `off` — the device's XMOS already filters |
| `mcp_tool_allowlist` | Trim the toolset for speed/cost |

Recordings in `/share/voice-enrollment` and `/share/voice-probes` are personal
data: they stay on your machine and are never uploaded by this add-on.

---
*Based on / inspired by xandervanerven's and fjfricke's ha-openai-realtime — with thanks.*
