#!/usr/bin/env python3
"""
Convert a Claude Code session transcript (.jsonl) into an axm-chat import file.

Pure stdlib — no axm dependency, so it runs anywhere. It extracts the literal
UTTERANCES of a session: every real user prose turn and every assistant text
block, verbatim, in order. It deliberately drops the machinery — tool_use calls,
tool_result dumps, thinking blocks, injected <system-reminder> tags, attachments
— because those aren't things that were *said*, and they'd bloat the shard
without carrying decisions. What remains is the byte-exact conversation, ready
for `axm-chat import` (see memory/README.md for the full seal loop).

    python memory/transcript_to_export.py SESSION.jsonl -o export.json
    python memory/transcript_to_export.py SESSION.jsonl --stats   # inspect, write nothing

The Claude Code transcript path is typically:
    ~/.claude/projects/<slug>/<session-uuid>.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SYS_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def _text_blocks(content) -> str | None:
    """Concatenated verbatim text from a message's content (str or block list),
    excluding tool_use / tool_result / thinking / image. None if nothing said."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = [b["text"] for b in content
             if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
    return "\n".join(p for p in parts if p.strip()) or None


def _is_tool_result(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def extract_utterances(transcript_path: str | Path) -> list[dict]:
    """Return the ordered list of real utterances: {role, content, created_at}."""
    turns: list[dict] = []
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") not in ("user", "assistant"):
                continue
            m = o.get("message", {})
            role, content = m.get("role"), m.get("content")
            if role == "user" and _is_tool_result(content):
                continue  # a tool result wearing the user role — not an utterance
            txt = _text_blocks(content)
            if not txt:
                continue
            txt = SYS_REMINDER.sub("", txt).strip()
            if not txt or txt.startswith("<command-") or txt.startswith("Caveat:"):
                continue
            turns.append({"role": "human" if role == "user" else "assistant",
                          "content": txt, "created_at": o.get("timestamp") or ""})

    # collapse consecutive same-role fragments (one turn split across text blocks)
    merged: list[dict] = []
    for t in turns:
        if merged and merged[-1]["role"] == t["role"]:
            merged[-1]["content"] += "\n\n" + t["content"]
            merged[-1]["created_at"] = t["created_at"] or merged[-1]["created_at"]
        else:
            merged.append(dict(t))
    return merged


def to_export(utterances: list[dict], name: str, uuid: str) -> list[dict]:
    """Wrap utterances in the Claude-export shape axm-chat's importer detects."""
    return [{
        "uuid": uuid,
        "name": name,
        "created_at": utterances[0]["created_at"] if utterances else "",
        "chat_messages": [{"sender": t["role"], "text": t["content"], "created_at": t["created_at"]}
                          for t in utterances],
    }]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", help="path to a Claude Code session .jsonl")
    ap.add_argument("-o", "--out", help="output export.json path")
    ap.add_argument("--name", default=None, help="conversation name for the shard")
    ap.add_argument("--stats", action="store_true", help="print counts; write nothing")
    a = ap.parse_args()

    utt = extract_utterances(a.transcript)
    chars = sum(len(t["content"]) for t in utt)
    human = sum(1 for t in utt if t["role"] == "human")
    if a.stats:
        print(f"utterances: {len(utt)} (human {human}, assistant {len(utt) - human})")
        print(f"chars: {chars:,}  (~{chars // 4:,} tokens)")
        return
    stem = Path(a.transcript).stem
    export = to_export(utt, a.name or f"session {stem}", f"claude-code-session-{stem}")
    out = a.out or f"{stem}.export.json"
    Path(out).write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}: {len(utt)} verbatim utterances, {chars:,} chars")
    print("next: axm-chat import " + out)


if __name__ == "__main__":
    main()
