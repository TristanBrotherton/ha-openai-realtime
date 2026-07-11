"""Voice-instructed persistent memory: the household teaches the assistant.

"Remember that..." appends a note to /share/voice-memory/memory.md (shared by
all device instances, survives rebuilds). Notes are speaker-attributed via the
voice verdict and folded into the system instructions at every session
creation, so spoken guidance becomes standing behavior — self-improvement by
voice. "Forget..." removes matching notes; "what do you remember" lists them.

Guardrails: only identified household speakers can add/remove (unknown/guest
voices are refused); hard caps keep the prompt overhead bounded.
"""
import logging
import os
import re
import time
from typing import Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

MEM_PATH = "/share/voice-memory/memory.md"
MAX_NOTES = 60
MAX_NOTE_CHARS = 300


def _load() -> list:
    try:
        lines = [l for l in open(MEM_PATH).read().splitlines() if l.startswith("- ")]
        return lines[-MAX_NOTES:]
    except FileNotFoundError:
        return []


def _save(lines: list) -> None:
    os.makedirs(os.path.dirname(MEM_PATH), exist_ok=True)
    with open(MEM_PATH, "w") as f:
        f.write("# Voice-instructed memory (managed by the assistant)\n")
        f.write("\n".join(lines[-MAX_NOTES:]) + "\n")


def memory_instructions() -> str:
    """The block appended to session instructions."""
    notes = _load()
    if not notes:
        return ""
    return (
        "\n\nHOUSEHOLD MEMORY (standing notes the household asked you to keep; "
        "follow them):\n" + "\n".join(notes)
    )


def get_memory_tool_definitions() -> list:
    return [
        {"type": "function", "name": "remember",
         "description": ("Store a standing note/instruction/preference the household asks you "
                         "to remember ('remember that...', 'from now on...'). It becomes part "
                         "of your instructions in every future conversation."),
         "parameters": {"type": "object", "properties": {
             "note": {"type": "string", "description": "The note, concise, third person"}},
             "required": ["note"]}},
        {"type": "function", "name": "forget",
         "description": "Remove remembered notes matching a phrase ('forget about the bins').",
         "parameters": {"type": "object", "properties": {
             "matching": {"type": "string", "description": "Word/phrase identifying the note(s)"}},
             "required": ["matching"]}},
        {"type": "function", "name": "list_memories",
         "description": "List everything the household asked you to remember.",
         "parameters": {"type": "object", "properties": {}}},
    ]


def register_memory_tools(llm, get_speaker_name: Optional[Callable[[], Optional[str]]]) -> None:
    def _speaker() -> Optional[str]:
        if get_speaker_name is None:
            return None
        try:
            return get_speaker_name()
        except Exception:
            return None

    async def _remember(params) -> None:
        note = ((params.arguments or {}).get("note") or "").strip()[:MAX_NOTE_CHARS]
        who = _speaker()
        if not who:
            await params.result_callback({"error": (
                "Memory changes are reserved for identified household members, and "
                "the current speaker's voice was not recognized. Decline politely.")})
            return
        if not note:
            await params.result_callback({"error": "empty note"})
            return
        lines = _load()
        lines.append(f"- {note} (from {who}, {time.strftime('%Y-%m-%d')})")
        _save(lines)
        logger.info(f"🧠 remembered ({who}): {note}")
        await params.result_callback({"status": "remembered",
                                      "note": "Active in all future conversations; confirm briefly."})

    async def _forget(params) -> None:
        pat = ((params.arguments or {}).get("matching") or "").strip()
        who = _speaker()
        if not who:
            await params.result_callback({"error": "Memory changes are reserved for identified household members."})
            return
        lines = _load()
        keep = [l for l in lines if pat.lower() not in l.lower()]
        removed = len(lines) - len(keep)
        _save(keep)
        logger.info(f"🧠 forgot {removed} note(s) matching '{pat}' ({who})")
        await params.result_callback({"removed": removed})

    async def _list(params) -> None:
        await params.result_callback({"memories": _load() or ["nothing yet"]})

    llm.register_function("remember", _remember)
    llm.register_function("forget", _forget)
    llm.register_function("list_memories", _list)
