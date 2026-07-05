"""Generate a Google Calendar-subscribable .ics feed of Pokemon GO events.

Data source: ScrapedDuck (https://github.com/bigfoott/ScrapedDuck), which
scrapes LeekDuck event listings. Stdlib only by design - see the spec in
docs/superpowers/specs/.
"""

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

EVENTS_URL = "https://raw.githubusercontent.com/bigfoott/ScrapedDuck/data/events.min.json"
REPO_ROOT = Path(__file__).parent

# --- ICS text primitives (RFC 5545 sections 3.3.11 and 3.1) ---


def escape_text(value: str) -> str:
    """Escape a string for use as an ICS TEXT property value."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> str:
    """Fold a content line to physical lines of at most 75 octets (UTF-8 safe).

    Continuation lines begin with a single space that counts toward the limit.
    """
    parts = []
    current = ""
    octets = 0
    for ch in line:
        ch_octets = len(ch.encode("utf-8"))
        if octets + ch_octets > 75:
            parts.append(current)
            current = " "
            octets = 1
        current += ch
        octets += ch_octets
    parts.append(current)
    return "\r\n".join(parts)
