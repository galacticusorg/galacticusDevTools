#!/usr/bin/env python3
"""Claude Code statusLine command that records plan-usage data for usageGate.py.

Claude Code passes a JSON object on stdin to the statusLine command. For
claude.ai subscribers it includes (after the first API response of a session)

    rate_limits.five_hour.used_percentage, rate_limits.five_hour.resets_at
    rate_limits.seven_day.used_percentage, rate_limits.seven_day.resets_at

(percentages 0-100, reset times as Unix epoch seconds; see
https://code.claude.com/docs/en/statusline). This script saves that object,
with the time it was received, to `$AUDIT_USAGE_FILE` (default
`~/.cache/claude-usage/usage.json`), and then either runs the command in
`$AUDIT_STATUSLINE_NEXT` (your normal status line, given the same stdin) or
prints a short status line of its own.

Install in ~/.claude/settings.json:

    "statusLine": {"type": "command", "command": "/path/to/statuslineUsage.py"}

Usage is per account, so any session on the machine keeps the file fresh.
"""
import json
import os
import subprocess
import sys
import tempfile
import time


def usage_file():
    return os.environ.get("AUDIT_USAGE_FILE") or os.path.expanduser("~/.cache/claude-usage/usage.json")


def record(data):
    limits = data.get("rate_limits")
    if not isinstance(limits, dict) or not isinstance(limits.get("seven_day"), dict):
        return None  # nothing usable yet (no API response, or not a subscriber): keep the previous reading
    path = os.path.abspath(usage_file())
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    payload = {"written": time.time(), "session_id": data.get("session_id"), "rate_limits": limits}
    handle, temporary = tempfile.mkstemp(prefix=".usage-", dir=directory)
    with os.fdopen(handle, "w") as stream:
        json.dump(payload, stream)
    os.replace(temporary, path)
    return limits


def short_line(limits):
    parts = []
    for key, label in (("seven_day", "7d"), ("five_hour", "5h")):
        window = (limits or {}).get(key) or {}
        if window.get("used_percentage") is not None:
            parts.append("{} {:.0f}%".format(label, window["used_percentage"]))
    return " · ".join(parts)


def main():
    raw = sys.stdin.read()
    limits = None
    try:
        limits = record(json.loads(raw))
    except Exception:  # a status line must never fail loudly
        pass
    following = os.environ.get("AUDIT_STATUSLINE_NEXT")
    if following:
        result = subprocess.run(following, shell=True, input=raw, universal_newlines=True,
                                stdout=subprocess.PIPE)
        sys.stdout.write(result.stdout)
    else:
        print(short_line(limits))


if __name__ == "__main__":
    main()
