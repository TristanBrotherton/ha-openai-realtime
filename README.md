# OpenAI Realtime Voice Agent — ha-mcp + Voice PE fork

Voice control for Home Assistant using the **OpenAI Realtime API** with
ESP32-S3 devices.

> **Fork of [`fjfricke/ha-openai-realtime`](https://github.com/fjfricke/ha-openai-realtime).**
> Changes in this fork:
> - Model defaults to **`gpt-realtime-2`** (configurable via `openai_model`).
> - Home Assistant control via the unofficial
>   **[ha-mcp](https://github.com/homeassistant-ai/ha-mcp)** server (set
>   `ha_mcp_url` + `longlived_token`); optional `mcp_tool_allowlist` to trim
>   ha-mcp's 80+ tools for a faster realtime session.
> - Speaks the **`maxmaxme` `va_client` wire protocol** so it pairs with the
>   polished Voice PE firmware at
>   [xandervanerven/home-assistant-voice-pe](https://github.com/xandervanerven/home-assistant-voice-pe):
>   sends `hello`/`phase`/`pong`, accepts `start`/`ping`/`interrupt`, and
>   resamples the device's 16 kHz mic up to 24 kHz.
> - **Handsfree barge-in**: the firmware keeps the mic open during replies; this
>   add-on's server-VAD interrupts the response when you talk over it.
> - Builds **locally** from the Dockerfile (no `image:` key) so the fork works
>   without publishing to a registry.

## Components

This repository contains two main components:

- **Server** (`openai_realtime_voice_agent/`): Home Assistant addon that provides OpenAI Realtime API integration and WebSocket server for ESP32 devices
- **Client** (`home-assistant-voice-pe/`): the original fjfricke ESPHome client (kept for reference). For this fork, flash the **maxmaxme-based firmware** at [xandervanerven/home-assistant-voice-pe](https://github.com/xandervanerven/home-assistant-voice-pe) instead.

## Features

### Server Features

- **OpenAI Realtime API Integration**: Direct integration with OpenAI's Realtime API for natural language interactions
- **WebSocket Server**: Bidirectional WebSocket connection for ESP32 devices with low latency
- **Home Assistant MCP Integration**: Integration with Model Context Protocol for smart home control
- **Voice Activity Detection (VAD)**: Automatic detection of speech vs. silence for optimal conversation flow
- **Session Management**: Automatic session reuse for better performance and conversation continuity
- **Audio Recording**: Optional audio recording for debugging purposes

### Client Features

- **Voice Assistant**: Real-time voice interaction with OpenAI Realtime API via WebSocket
- **Wake Word Detection**: Multiple wake words supported ("Okay Nabu", "Hey Jarvis", "Hey Mycroft")
- **LED Feedback**: Visual status indicators via 12-LED ring for various states
- **Hardware Controls**: Button controls and hardware mute switch for privacy
- **Auto Gain Control (AGC)**: Hardware-based automatic volume adjustment for consistent audio quality
- **Echo Cancellation (AEC)**: Hardware-based echo suppression prevents feedback

### Conversation Behavior

- **Immediate Response**: After wake word detection, you can speak immediately without waiting
- **Natural Conversation Flow**: During silence, you can continue speaking naturally - the assistant listens continuously
- **Interruption Handling**: User input during assistant responses is ignored, except for wake words which can interrupt
- **Stop Words**: Conversation ends when a stop word is detected (e.g., "thank you", "stop") using a dedicated tool
- **Session Continuity**: Previous conversation history is maintained when a new wake word is spoken within the session reuse timeout period after the last conversation ended
- **Wake Word Restart**: After a conversation ends, a new wake word starts a fresh interaction while preserving context within the timeout window

## Documentation

- **Server Installation**: See [`openai_realtime_voice_agent/README.md`](openai_realtime_voice_agent/README.md)
- **Client Installation**: See [`home-assistant-voice-pe/README.md`](home-assistant-voice-pe/README.md)

## Quick Start

1. **Install the Server Addon**: Follow the [server documentation](openai_realtime_voice_agent/README.md)
2. **Configure ESP32 Device**: Follow the [client documentation](home-assistant-voice-pe/README.md)

## Home Assistant control via ha-mcp

This fork targets the unofficial [ha-mcp](https://github.com/homeassistant-ai/ha-mcp)
server (far more capable than HA's built-in MCP — it can create automations,
scripts, scenes, dashboards, query history, etc.). Configure the add-on with:

- `ha_mcp_url`: ha-mcp's Streamable-HTTP endpoint, e.g.
  `http://homeassistant.local:8086/mcp` (run ha-mcp as its own add-on/container).
- `longlived_token`: a Home Assistant long-lived access token.
- `mcp_tool_allowlist` (optional): comma-separated tool names to expose.

To use HA's **built-in** MCP instead, leave `ha_mcp_url` blank (defaults to
`http://supervisor/core/api/mcp`) and enable the *Model Context Protocol Server*
integration in Home Assistant. Note the built-in `supervisor` endpoint can be
flaky — if so, set `ha_mcp_url` to `http://homeassistant.local:8123/api/mcp` and
provide a `longlived_token`.

## Add-on install

Add this repository to **Settings → Add-ons → Add-on store → ⋮ → Repositories**
(`https://github.com/xandervanerven/ha-openai-realtime`), then install
*OpenAI Realtime Voice Agent*. The add-on has no prebuilt `image:`, so Home
Assistant builds it locally on first install (this can take several minutes on a
Raspberry Pi). Advanced users can publish images via the included GitHub Actions
workflow and re-add an `image:` key to `config.yaml` for faster installs.

## License

MIT License - see [LICENSE](LICENSE) file for details.
