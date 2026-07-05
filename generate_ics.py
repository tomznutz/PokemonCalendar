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


# --- Datetime handling ---
# ScrapedDuck times are usually timezone-less, meaning "local time wherever
# the player is" (e.g. Community Day at 14:00 everywhere). Those become
# floating ICS times. A trailing "Z" marks a genuinely global UTC moment.


def parse_dt(value: str) -> tuple[datetime, bool]:
    """Parse an ISO 8601 string into a naive datetime plus an is_utc flag."""
    if value.endswith("Z"):
        return datetime.fromisoformat(value[:-1]), True
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None), True
    return dt, False


def format_dt(dt: datetime, is_utc: bool) -> str:
    """Format a naive datetime as an ICS DATE-TIME (floating or UTC)."""
    formatted = dt.strftime("%Y%m%dT%H%M%S")
    return formatted + "Z" if is_utc else formatted


# --- Event selection ---


def normalize_times(event: dict) -> tuple[datetime, bool, datetime, bool]:
    """Return (start, start_is_utc, end, end_is_utc); end defaults to start+1h."""
    start, start_utc = parse_dt(event["start"])
    if event.get("end"):
        end, end_utc = parse_dt(event["end"])
    else:
        end, end_utc = start + timedelta(hours=1), start_utc
    return start, start_utc, end, end_utc


def filter_events(events: list[dict], included_types: set[str]) -> list[dict]:
    """Keep allowlisted events whose times are present and parseable."""
    kept = []
    for event in events:
        if event.get("eventType") not in included_types:
            continue
        if not event.get("start"):
            print(f"warning: skipping {event.get('eventID')!r}: no start time", file=sys.stderr)
            continue
        try:
            start, _, end, _ = normalize_times(event)
        except ValueError:
            print(f"warning: skipping {event.get('eventID')!r}: bad datetime", file=sys.stderr)
            continue
        if end < start:
            print(f"warning: skipping {event.get('eventID')!r}: end before start", file=sys.stderr)
            continue
        kept.append(event)
    return kept


# --- Calendar event content ---


def _texts(items: list | None, key: str = "name") -> list[str]:
    """Pull a text field from a list of dicts, skipping items that lack it."""
    return [item.get(key) for item in items or [] if item.get(key)]


def build_description(event: dict) -> str:
    """Assemble a plain-text description from the event's extraData.

    ✨ marks Pokemon that can be shiny. Unknown extraData shapes are ignored
    so upstream additions never break generation.
    """
    lines = [event.get("heading") or event.get("eventType") or "Event"]
    extra = event.get("extraData") or {}

    community_day = extra.get("communityday") or {}
    spawns = _texts(community_day.get("spawns"))
    if spawns:
        lines.append("Featured: " + ", ".join(spawns))
    bonuses = _texts(community_day.get("bonuses"), key="text")
    if bonuses:
        lines.append("Bonuses:")
        lines.extend("• " + bonus for bonus in bonuses)
    shinies = _texts(community_day.get("shinies"))
    if shinies:
        lines.append("Shinies: " + ", ".join(shinies) + " ✨")

    raid_battles = extra.get("raidbattles") or {}
    bosses = [
        name + (" ✨" if boss.get("canBeShiny") else "")
        for boss in raid_battles.get("bosses") or []
        for name in [boss.get("name")]
        if name
    ]
    if bosses:
        lines.append("Bosses: " + ", ".join(bosses))

    spotlight = extra.get("spotlight") or {}
    if spotlight.get("name"):
        lines.append(
            "Featured: " + spotlight["name"] + (" ✨" if spotlight.get("canBeShiny") else "")
        )
    if spotlight.get("bonus"):
        lines.append("Bonus: " + spotlight["bonus"])

    breakthrough = extra.get("breakthrough") or {}
    if breakthrough.get("name"):
        lines.append(
            "Reward: " + breakthrough["name"] + (" ✨" if breakthrough.get("canBeShiny") else "")
        )

    if event.get("link"):
        lines.append("")
        lines.append(event["link"])
    return "\n".join(lines)
