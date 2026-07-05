# Pokemon GO Calendar Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a subscribable `events.ics` Google Calendar feed of Pokemon GO events from the ScrapedDuck API, auto-refreshed by GitHub Actions.

**Architecture:** A single dependency-free Python script (`generate_ics.py`) fetches `events.min.json` from ScrapedDuck, filters events to an allowlist of event types in `config.json`, and emits an RFC 5545 `events.ics`. A scheduled GitHub Actions workflow regenerates and commits the file every 12 hours; Google Calendar subscribes to the raw file URL.

**Tech Stack:** Python 3.11+ standard library only (`urllib`, `json`, `datetime`, `unittest`). GitHub Actions for scheduling.

**Spec:** `docs/superpowers/specs/2026-07-05-pokemon-go-calendar-feed-design.md`

---

## Reference: ScrapedDuck event shapes (verified against live feed 2026-07-05)

Feed URL: `https://raw.githubusercontent.com/bigfoott/ScrapedDuck/data/events.min.json` — a JSON array of objects:

```json
{
  "eventID": "july-communityday2026",
  "name": "Sobble Community Day",
  "eventType": "community-day",
  "heading": "Community Day",
  "link": "https://leekduck.com/events/july-communityday2026/",
  "image": "https://cdn.leekduck.com/...jpg",
  "start": "2026-07-04T14:00:00",
  "end": "2026-07-04T17:00:00",
  "extraData": { ... }
}
```

- `start`/`end` are ISO 8601 strings, **nullable**. Usually timezone-less (= local time wherever the player is); occasionally suffixed `Z` (= UTC, global events).
- `extraData` keys observed in the live feed: `generic` (always), plus type-specific:
  - `communityday`: `spawns: [{name, image}]`, `bonuses: [{text, image}]`, `bonusDisclaimers: [str]`, `shinies: [{name, image}]`, `specialresearch: [...]`
  - `raidbattles`: `bosses: [{name, image, canBeShiny}]`, `shinies: [{name, image}]`
  - `spotlight`: `name: str`, `canBeShiny: bool`, `image: str`, `bonus: str`, `list: [{name, canBeShiny, image}]`
  - `breakthrough` (documented in wiki, not currently in feed): `name: str`, `canBeShiny: bool`
- `extraData` may be null/missing on some events — code must tolerate that.

## File structure

```
PokemonCalendar/
├── generate_ics.py               # everything: ICS primitives, event processing, fetch, main
├── config.json                   # calendar name + eventType allowlist
├── events.ics                    # generated output (committed)
├── tests/
│   └── test_generate.py          # unittest suite for generate_ics.py
├── .github/workflows/update.yml  # scheduled regeneration workflow
└── README.md                     # what this is + subscribe instructions
```

One module is appropriate: the script is ~150 lines with clear internal sections (text primitives → datetime handling → event processing → I/O), and a single file keeps the Actions workflow and local runs trivial.

All test commands below are run from the repo root: `C:\Users\Admin\Documents\Projects\PokemonCalendar`.

---

### Task 1: Project scaffolding (config + module skeleton)

**Files:**
- Create: `config.json`
- Create: `generate_ics.py`
- Create: `tests/test_generate.py`

- [ ] **Step 1: Create `config.json`**

```json
{
  "calendarName": "Pokémon GO Events",
  "includedEventTypes": [
    "community-day",
    "raid-day",
    "raid-hour",
    "pokemon-spotlight-hour",
    "max-mondays",
    "research",
    "raid-battles",
    "elite-raids",
    "pokemon-go-fest",
    "event",
    "choose-your-path",
    "research-breakthrough",
    "ticketed-event",
    "location-specific",
    "live-event",
    "bonus-hour",
    "go-tour",
    "safari-zone"
  ]
}
```

- [ ] **Step 2: Create `generate_ics.py` skeleton**

```python
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
```

- [ ] **Step 3: Create `tests/test_generate.py` skeleton**

```python
import unittest

import generate_ics


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Verify the test file runs (0 tests, no errors)**

Run: `python -m unittest discover -s tests -v`
Expected: `Ran 0 tests` / `OK` (imports succeed; note discovery runs from repo root so `generate_ics` is importable)

- [ ] **Step 5: Commit**

```bash
git add config.json generate_ics.py tests/test_generate.py
git commit -m "feat: scaffold config and generator skeleton"
```

---

### Task 2: ICS text primitives — escaping and line folding

**Files:**
- Modify: `generate_ics.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write failing tests for `escape_text` and `fold_line`**

Add to `tests/test_generate.py` (above the `__main__` block):

```python
class EscapeTextTests(unittest.TestCase):
    def test_plain_text_unchanged(self):
        self.assertEqual(generate_ics.escape_text("Raid Hour"), "Raid Hour")

    def test_escapes_special_characters(self):
        self.assertEqual(
            generate_ics.escape_text(r"a\b;c,d"),
            r"a\\b\;c\,d",
        )

    def test_escapes_newlines(self):
        self.assertEqual(generate_ics.escape_text("a\nb\r\nc"), r"a\nb\nc")


class FoldLineTests(unittest.TestCase):
    def test_short_line_unchanged(self):
        self.assertEqual(generate_ics.fold_line("SUMMARY:Raid Hour"), "SUMMARY:Raid Hour")

    def test_line_at_75_octets_unchanged(self):
        line = "X" * 75
        self.assertEqual(generate_ics.fold_line(line), line)

    def test_long_line_folds_with_leading_space(self):
        line = "DESCRIPTION:" + "A" * 100
        folded = generate_ics.fold_line(line)
        physical = folded.split("\r\n")
        self.assertEqual(physical[0], "DESCRIPTION:" + "A" * 63)  # 75 octets
        self.assertTrue(physical[1].startswith(" "))
        # Unfolding (strip leading space, rejoin) restores the original.
        self.assertEqual(physical[0] + "".join(p[1:] for p in physical[1:]), line)

    def test_every_physical_line_is_at_most_75_octets(self):
        line = "DESCRIPTION:" + "é" * 100  # 2-byte UTF-8 chars
        for physical in generate_ics.fold_line(line).split("\r\n"):
            self.assertLessEqual(len(physical.encode("utf-8")), 75)

    def test_never_splits_a_multibyte_character(self):
        line = "X" * 74 + "é" + "Y" * 10  # é would straddle the 75-octet boundary
        for physical in generate_ics.fold_line(line).split("\r\n"):
            physical.encode("utf-8").decode("utf-8")  # raises if a char was split
        unfolded = "".join(
            p[1:] if i else p
            for i, p in enumerate(generate_ics.fold_line(line).split("\r\n"))
        )
        self.assertEqual(unfolded, line)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL with `AttributeError: module 'generate_ics' has no attribute 'escape_text'`

- [ ] **Step 3: Implement `escape_text` and `fold_line` in `generate_ics.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add generate_ics.py tests/test_generate.py
git commit -m "feat: add RFC 5545 text escaping and line folding"
```

---

### Task 3: Datetime parsing and formatting (floating vs UTC)

**Files:**
- Modify: `generate_ics.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_generate.py`:

```python
from datetime import datetime


class DatetimeTests(unittest.TestCase):
    def test_parse_local_datetime_is_floating(self):
        dt, is_utc = generate_ics.parse_dt("2026-07-04T14:00:00")
        self.assertEqual(dt, datetime(2026, 7, 4, 14, 0, 0))
        self.assertFalse(is_utc)

    def test_parse_utc_datetime(self):
        dt, is_utc = generate_ics.parse_dt("2026-07-04T14:00:00Z")
        self.assertEqual(dt, datetime(2026, 7, 4, 14, 0, 0))
        self.assertTrue(is_utc)

    def test_format_floating(self):
        dt = datetime(2026, 7, 4, 14, 0, 0)
        self.assertEqual(generate_ics.format_dt(dt, is_utc=False), "20260704T140000")

    def test_format_utc(self):
        dt = datetime(2026, 7, 4, 14, 0, 0)
        self.assertEqual(generate_ics.format_dt(dt, is_utc=True), "20260704T140000Z")
```

(The `from datetime import datetime` import goes at the top of the test file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL with `AttributeError: module 'generate_ics' has no attribute 'parse_dt'`

- [ ] **Step 3: Implement `parse_dt` and `format_dt`**

```python
# --- Datetime handling ---
# ScrapedDuck times are usually timezone-less, meaning "local time wherever
# the player is" (e.g. Community Day at 14:00 everywhere). Those become
# floating ICS times. A trailing "Z" marks a genuinely global UTC moment.

def parse_dt(value: str) -> tuple[datetime, bool]:
    """Parse an ISO 8601 string into a naive datetime plus an is_utc flag."""
    if value.endswith("Z"):
        return datetime.fromisoformat(value[:-1]), True
    return datetime.fromisoformat(value), False


def format_dt(dt: datetime, is_utc: bool) -> str:
    """Format a naive datetime as an ICS DATE-TIME (floating or UTC)."""
    formatted = dt.strftime("%Y%m%dT%H%M%S")
    return formatted + "Z" if is_utc else formatted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add generate_ics.py tests/test_generate.py
git commit -m "feat: parse and format floating/UTC datetimes"
```

---

### Task 4: Event filtering and time normalization

**Files:**
- Modify: `generate_ics.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_generate.py`:

```python
from datetime import timedelta


def make_event(**overrides):
    """A minimal valid ScrapedDuck event for tests."""
    event = {
        "eventID": "test-event-1",
        "name": "Test Event",
        "eventType": "raid-hour",
        "heading": "Raid Hour",
        "link": "https://leekduck.com/events/test-event-1/",
        "image": "https://example.com/img.jpg",
        "start": "2026-07-15T18:00:00",
        "end": "2026-07-15T19:00:00",
        "extraData": {"generic": {"hasSpawns": False, "hasFieldResearchTasks": False}},
    }
    event.update(overrides)
    return event


class FilterEventsTests(unittest.TestCase):
    def test_keeps_allowlisted_types_only(self):
        events = [
            make_event(eventID="a", eventType="raid-hour"),
            make_event(eventID="b", eventType="go-battle-league"),
            make_event(eventID="c", eventType="community-day"),
        ]
        kept = generate_ics.filter_events(events, {"raid-hour", "community-day"})
        self.assertEqual([e["eventID"] for e in kept], ["a", "c"])

    def test_skips_event_with_no_start(self):
        events = [make_event(start=None)]
        self.assertEqual(generate_ics.filter_events(events, {"raid-hour"}), [])

    def test_skips_event_with_unparseable_start(self):
        events = [make_event(start="not-a-date"), make_event(eventID="ok")]
        kept = generate_ics.filter_events(events, {"raid-hour"})
        self.assertEqual([e["eventID"] for e in kept], ["ok"])


class NormalizeTimesTests(unittest.TestCase):
    def test_start_and_end_parsed(self):
        start, start_utc, end, end_utc = generate_ics.normalize_times(make_event())
        self.assertEqual(start, datetime(2026, 7, 15, 18, 0, 0))
        self.assertEqual(end, datetime(2026, 7, 15, 19, 0, 0))
        self.assertFalse(start_utc)
        self.assertFalse(end_utc)

    def test_missing_end_defaults_to_one_hour(self):
        start, start_utc, end, end_utc = generate_ics.normalize_times(
            make_event(end=None)
        )
        self.assertEqual(end - start, timedelta(hours=1))
        self.assertEqual(end_utc, start_utc)

    def test_utc_event(self):
        start, start_utc, end, end_utc = generate_ics.normalize_times(
            make_event(start="2026-07-15T18:00:00Z", end="2026-07-15T19:00:00Z")
        )
        self.assertTrue(start_utc)
        self.assertTrue(end_utc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL with `AttributeError: module 'generate_ics' has no attribute 'filter_events'`

- [ ] **Step 3: Implement `filter_events` and `normalize_times`**

```python
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
            normalize_times(event)
        except ValueError:
            print(f"warning: skipping {event.get('eventID')!r}: bad datetime", file=sys.stderr)
            continue
        kept.append(event)
    return kept
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add generate_ics.py tests/test_generate.py
git commit -m "feat: filter events by type and normalize start/end times"
```

---

### Task 5: Description assembly from extraData

**Files:**
- Modify: `generate_ics.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_generate.py`:

```python
class BuildDescriptionTests(unittest.TestCase):
    def test_generic_event_has_heading_and_link(self):
        desc = generate_ics.build_description(make_event())
        self.assertIn("Raid Hour", desc)
        self.assertIn("https://leekduck.com/events/test-event-1/", desc)

    def test_community_day(self):
        event = make_event(
            heading="Community Day",
            extraData={
                "communityday": {
                    "spawns": [{"name": "Sobble", "image": "x"}],
                    "bonuses": [
                        {"text": "Increased Spawns", "image": "x"},
                        {"text": "2x Catch Candy", "image": "x"},
                    ],
                    "shinies": [
                        {"name": "Sobble", "image": "x"},
                        {"name": "Drizzile", "image": "x"},
                    ],
                },
                "generic": {"hasSpawns": True, "hasFieldResearchTasks": True},
            },
        )
        desc = generate_ics.build_description(event)
        self.assertIn("Featured: Sobble", desc)
        self.assertIn("• Increased Spawns", desc)
        self.assertIn("• 2x Catch Candy", desc)
        self.assertIn("Shinies: Sobble, Drizzile ✨", desc)

    def test_raid_battles_marks_shiny_bosses(self):
        event = make_event(
            extraData={
                "raidbattles": {
                    "bosses": [
                        {"name": "Articuno", "image": "x", "canBeShiny": True},
                        {"name": "Zapdos", "image": "x", "canBeShiny": False},
                    ],
                    "shinies": [],
                },
                "generic": {"hasSpawns": False, "hasFieldResearchTasks": False},
            }
        )
        desc = generate_ics.build_description(event)
        self.assertIn("Bosses: Articuno ✨, Zapdos", desc)

    def test_spotlight_hour(self):
        event = make_event(
            extraData={
                "spotlight": {
                    "name": "Zubat",
                    "canBeShiny": True,
                    "image": "x",
                    "bonus": "2× Catch XP",
                    "list": [{"name": "Zubat", "canBeShiny": True, "image": "x"}],
                },
                "generic": {"hasSpawns": True, "hasFieldResearchTasks": False},
            }
        )
        desc = generate_ics.build_description(event)
        self.assertIn("Featured: Zubat ✨", desc)
        self.assertIn("Bonus: 2× Catch XP", desc)

    def test_breakthrough(self):
        event = make_event(
            extraData={
                "breakthrough": {"name": "Galarian Mr. Mime", "canBeShiny": False},
                "generic": {"hasSpawns": False, "hasFieldResearchTasks": False},
            }
        )
        desc = generate_ics.build_description(event)
        self.assertIn("Reward: Galarian Mr. Mime", desc)
        self.assertNotIn("Galarian Mr. Mime ✨", desc)

    def test_tolerates_missing_extra_data(self):
        desc = generate_ics.build_description(make_event(extraData=None))
        self.assertIn("Raid Hour", desc)

    def test_tolerates_missing_link(self):
        desc = generate_ics.build_description(make_event(link=None))
        self.assertIn("Raid Hour", desc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL with `AttributeError: module 'generate_ics' has no attribute 'build_description'`

- [ ] **Step 3: Implement `build_description`**

```python
# --- Calendar event content ---

def build_description(event: dict) -> str:
    """Assemble a plain-text description from the event's extraData.

    ✨ marks Pokemon that can be shiny. Unknown extraData shapes are ignored
    so upstream additions never break generation.
    """
    lines = [event.get("heading") or event.get("eventType") or "Event"]
    extra = event.get("extraData") or {}

    community_day = extra.get("communityday") or {}
    spawns = [p["name"] for p in community_day.get("spawns") or []]
    if spawns:
        lines.append("Featured: " + ", ".join(spawns))
    bonuses = [b["text"] for b in community_day.get("bonuses") or []]
    if bonuses:
        lines.append("Bonuses:")
        lines.extend("• " + bonus for bonus in bonuses)
    shinies = [s["name"] for s in community_day.get("shinies") or []]
    if shinies:
        lines.append("Shinies: " + ", ".join(shinies) + " ✨")

    raid_battles = extra.get("raidbattles") or {}
    bosses = [
        boss["name"] + (" ✨" if boss.get("canBeShiny") else "")
        for boss in raid_battles.get("bosses") or []
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add generate_ics.py tests/test_generate.py
git commit -m "feat: build event descriptions from extraData"
```

---

### Task 6: VEVENT and VCALENDAR assembly

**Files:**
- Modify: `generate_ics.py`
- Test: `tests/test_generate.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_generate.py`:

```python
from datetime import timezone

TEST_NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
TEST_CONFIG = {"calendarName": "Pokémon GO Events", "includedEventTypes": ["raid-hour"]}


class BuildVeventTests(unittest.TestCase):
    def test_basic_vevent_properties(self):
        lines = generate_ics.build_vevent(make_event(), TEST_NOW)
        self.assertEqual(lines[0], "BEGIN:VEVENT")
        self.assertEqual(lines[-1], "END:VEVENT")
        self.assertIn("UID:test-event-1@scrapedduck", lines)
        self.assertIn("DTSTAMP:20260705T120000Z", lines)
        self.assertIn("DTSTART:20260715T180000", lines)
        self.assertIn("DTEND:20260715T190000", lines)
        self.assertIn("SUMMARY:Test Event", lines)
        self.assertIn("URL:https://leekduck.com/events/test-event-1/", lines)

    def test_summary_is_escaped(self):
        lines = generate_ics.build_vevent(make_event(name="Raids, Eggs; Fun"), TEST_NOW)
        self.assertIn(r"SUMMARY:Raids\, Eggs\; Fun", lines)

    def test_no_url_property_when_link_missing(self):
        lines = generate_ics.build_vevent(make_event(link=None), TEST_NOW)
        self.assertFalse(any(line.startswith("URL:") for line in lines))


class BuildCalendarTests(unittest.TestCase):
    def test_calendar_wraps_events(self):
        text = generate_ics.build_calendar([make_event()], TEST_CONFIG, TEST_NOW)
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(text.endswith("END:VCALENDAR\r\n"))
        self.assertIn("VERSION:2.0", text)
        self.assertIn("X-WR-CALNAME:Pokémon GO Events", text)
        self.assertIn("BEGIN:VEVENT", text)

    def test_uses_crlf_line_endings_only(self):
        text = generate_ics.build_calendar([make_event()], TEST_CONFIG, TEST_NOW)
        self.assertNotIn("\n", text.replace("\r\n", ""))

    def test_empty_calendar_is_valid(self):
        text = generate_ics.build_calendar([], TEST_CONFIG, TEST_NOW)
        self.assertIn("BEGIN:VCALENDAR", text)
        self.assertNotIn("BEGIN:VEVENT", text)

    def test_all_lines_at_most_75_octets(self):
        event = make_event(name="N" * 200)
        text = generate_ics.build_calendar([event], TEST_CONFIG, TEST_NOW)
        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL with `AttributeError: module 'generate_ics' has no attribute 'build_vevent'`

- [ ] **Step 3: Implement `build_vevent` and `build_calendar`**

```python
# --- ICS assembly ---

def build_vevent(event: dict, now: datetime) -> list[str]:
    """Build the folded content lines for one event."""
    start, start_utc, end, end_utc = normalize_times(event)
    properties = [
        ("BEGIN", "VEVENT"),
        ("UID", f"{event['eventID']}@scrapedduck"),
        ("DTSTAMP", now.strftime("%Y%m%dT%H%M%SZ")),
        ("DTSTART", format_dt(start, start_utc)),
        ("DTEND", format_dt(end, end_utc)),
        ("SUMMARY", escape_text(event["name"])),
        ("DESCRIPTION", escape_text(build_description(event))),
    ]
    if event.get("link"):
        properties.append(("URL", event["link"]))
    properties.append(("END", "VEVENT"))
    return [fold_line(f"{name}:{value}") for name, value in properties]


def build_calendar(events: list[dict], config: dict, now: datetime) -> str:
    """Build the complete ICS document as a CRLF-terminated string."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PokemonCalendar//ScrapedDuck//EN",
        "CALSCALE:GREGORIAN",
        fold_line("X-WR-CALNAME:" + escape_text(config["calendarName"])),
    ]
    for event in events:
        lines.extend(build_vevent(event, now))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add generate_ics.py tests/test_generate.py
git commit -m "feat: assemble VEVENT and VCALENDAR output"
```

---

### Task 7: Fetch, main entry point, and first generated events.ics

**Files:**
- Modify: `generate_ics.py`
- Test: `tests/test_generate.py`
- Create: `events.ics` (generated)

- [ ] **Step 1: Write failing tests for `main` (fetch injected, no network)**

Add to `tests/test_generate.py`:

```python
import tempfile
from pathlib import Path


class MainTests(unittest.TestCase):
    def _run_main(self, events):
        out_dir = Path(tempfile.mkdtemp())
        out_path = out_dir / "events.ics"
        generate_ics.main(fetch=lambda: events, output_path=out_path)
        return out_path

    def test_writes_ics_file(self):
        out_path = self._run_main([make_event(eventType="raid-hour")])
        text = out_path.read_bytes().decode("utf-8")
        self.assertIn("BEGIN:VCALENDAR\r\n", text)
        self.assertIn("UID:test-event-1@scrapedduck", text)

    def test_excluded_types_are_absent(self):
        out_path = self._run_main(
            [make_event(eventType="go-battle-league", eventID="gbl-1")]
        )
        self.assertNotIn("gbl-1", out_path.read_text(encoding="utf-8"))

    def test_empty_feed_exits_nonzero(self):
        with self.assertRaises(SystemExit):
            self._run_main([])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL with `AttributeError: module 'generate_ics' has no attribute 'main'`

- [ ] **Step 3: Implement `fetch_events` and `main`**

```python
# --- Fetch and entry point ---

def fetch_events(url: str = EVENTS_URL) -> list[dict]:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def main(fetch=fetch_events, output_path: Path = REPO_ROOT / "events.ics") -> None:
    config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    events = fetch()
    if not events:
        sys.exit("error: event feed is empty - upstream problem, keeping existing events.ics")
    included = filter_events(events, set(config["includedEventTypes"]))
    ics = build_calendar(included, config, datetime.now(timezone.utc))
    output_path.write_bytes(ics.encode("utf-8"))
    print(f"wrote {output_path} with {len(included)} of {len(events)} events")


if __name__ == "__main__":
    main()
```

(`write_bytes` avoids Windows newline translation mangling the CRLF line endings.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS

- [ ] **Step 5: Add live smoke test (opt-in via env var)**

Add to `tests/test_generate.py`:

```python
import os


@unittest.skipUnless(os.environ.get("LIVE_TESTS"), "set LIVE_TESTS=1 to run network tests")
class LiveFeedTests(unittest.TestCase):
    def test_live_feed_produces_events(self):
        events = generate_ics.fetch_events()
        self.assertGreater(len(events), 0)
        config = {"calendarName": "Test", "includedEventTypes": ["community-day", "raid-hour", "event", "raid-battles"]}
        included = generate_ics.filter_events(events, set(config["includedEventTypes"]))
        text = generate_ics.build_calendar(
            included, config, datetime.now(timezone.utc)
        )
        self.assertIn("BEGIN:VEVENT", text)
```

(`from datetime import timezone` is already imported in Task 6's test additions; `import os` goes at the top of the file.)

- [ ] **Step 6: Run full suite including live test**

Run (PowerShell): `$env:LIVE_TESTS = "1"; python -m unittest discover -s tests -v; Remove-Item Env:LIVE_TESTS`
Expected: all tests PASS including `LiveFeedTests`

- [ ] **Step 7: Generate the real events.ics and eyeball it**

Run: `python generate_ics.py`
Expected: `wrote ...events.ics with N of M events` where N > 10.

Open `events.ics` and check: starts with `BEGIN:VCALENDAR`, contains recognizable event names, community day events show bonuses in DESCRIPTION.

- [ ] **Step 8: Commit**

```bash
git add generate_ics.py tests/test_generate.py events.ics
git commit -m "feat: add fetch + main entry point and generate first events.ics"
```

---

### Task 8: GitHub Actions workflow + README

**Files:**
- Create: `.github/workflows/update.yml`
- Create: `README.md`

- [ ] **Step 1: Create `.github/workflows/update.yml`**

```yaml
name: Update calendar feed

on:
  schedule:
    - cron: "0 */12 * * *" # every 12 hours
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run tests
        run: python -m unittest discover -s tests

      - name: Regenerate events.ics
        run: python generate_ics.py

      - name: Commit if changed
        run: |
          if git diff --quiet events.ics; then
            echo "events.ics unchanged"
          else
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add events.ics
            git commit -m "chore: update events.ics"
            git push
          fi
```

- [ ] **Step 2: Validate workflow YAML parses**

Run: `python -c "import yaml" 2>$null; if ($?) { python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/update.yml').read_text()); print('valid')" } else { echo 'pyyaml not installed - reviewed manually' }`
Expected: `valid` (or manual review note — this is a nice-to-have, not a gate)

- [ ] **Step 3: Create `README.md`**

```markdown
# Pokemon GO Calendar

A subscribable Google Calendar feed of upcoming Pokémon GO events
(Community Days, Raid Hours, Spotlight Hours, and more).

Event data comes from [ScrapedDuck](https://github.com/bigfoott/ScrapedDuck),
which scrapes [LeekDuck](https://leekduck.com/events/). A GitHub Actions
workflow regenerates [`events.ics`](events.ics) every 12 hours.

## Subscribe in Google Calendar

1. Open [Google Calendar settings → Add calendar → From URL](https://calendar.google.com/calendar/u/0/r/settings/addbyurl).
2. Paste the raw feed URL:
   `https://raw.githubusercontent.com/<USER>/<REPO>/master/events.ics`
3. Click **Add calendar**. Events appear within a day and refresh automatically
   (Google polls subscribed calendars roughly every 12–48 hours).

Times shown as "floating" local times match Pokémon GO's local-time events
(e.g. Community Day 2:00 p.m. wherever you are).

## Choosing which events appear

Edit the `includedEventTypes` list in [`config.json`](config.json). Event type
names are listed in the [ScrapedDuck Events wiki](https://github.com/bigfoott/ScrapedDuck/wiki/Events).
Long-running types like `go-battle-league`, `season`, and `go-pass` are
excluded by default to keep the calendar readable.

## Development

```
python -m unittest discover -s tests   # run tests
python generate_ics.py                 # regenerate events.ics
```

No dependencies — Python 3.11+ standard library only.
```

(Replace `<USER>/<REPO>` with the real values when the GitHub repo exists — done during setup, Task 9.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/update.yml README.md
git commit -m "feat: add scheduled update workflow and README"
```

---

### Task 9: Publish to GitHub and subscribe (interactive with user)

This task needs the user's GitHub account; pause and coordinate.

**Files:**
- Modify: `README.md` (fill in real raw URL)

- [ ] **Step 1: Check GitHub CLI auth**

Run: `gh auth status`
If not authenticated: ask the user to run `! gh auth login` (interactive) or create the repo manually on github.com.

- [ ] **Step 2: Create repo and push**

```bash
gh repo create PokemonCalendar --public --source . --push
```

(Public repo required for the raw URL to be fetchable by Google Calendar without auth. Confirm with the user before creating.)

- [ ] **Step 3: Fill in the real raw URL in README.md**

Replace `<USER>/<REPO>` with the actual path, e.g.
`https://raw.githubusercontent.com/thomasghulbert/PokemonCalendar/master/events.ics`.
Commit and push:

```bash
git add README.md
git commit -m "docs: fill in real feed URL"
git push
```

- [ ] **Step 4: Trigger the workflow once and verify it succeeds**

```bash
gh workflow run "Update calendar feed"
gh run watch
```

Expected: run completes green.

- [ ] **Step 5: Hand the user the subscribe URL and instructions**

Give the user:
1. The raw URL to paste into Google Calendar → Settings → Add calendar → From URL.
2. Reminder that Google's first sync may take a few minutes, and refreshes lag 12–48 h.

---

## Self-review notes

- **Spec coverage:** data source ✓ (Task 7), filtering ✓ (Task 4 + config in Task 1), null-start skip / null-end +1h ✓ (Task 4), floating vs UTC ✓ (Task 3), UID dedup ✓ (Task 6), rich descriptions ✓ (Task 5), escaping/folding/CRLF ✓ (Task 2, 6), empty-feed exit ✓ (Task 7), workflow + failure mode ✓ (Task 8), user setup ✓ (Task 9). Season/GBL exclusion is via allowlist ✓.
- **`breakthrough` extraData** isn't in today's live feed but is in the wiki; handled defensively in Task 5 with a test.
- **Type consistency:** `filter_events(events, included_types: set)`, `normalize_times(event) -> (start, start_utc, end, end_utc)`, `build_vevent(event, now) -> list[str]`, `build_calendar(events, config, now) -> str`, `main(fetch, output_path)` — usage matches definitions across tasks.
