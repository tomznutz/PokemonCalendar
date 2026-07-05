# Pokemon GO → Google Calendar Feed — Design

**Date:** 2026-07-05
**Status:** Approved

## Goal

Keep a Google Calendar automatically populated with upcoming Pokemon GO events
(Community Days, raids, Spotlight Hours, etc.) using the ScrapedDuck events API,
with zero ongoing manual effort.

## Approach

Generate an iCalendar (`.ics`) file from ScrapedDuck data, commit it to a GitHub
repository, and regenerate it on a schedule with GitHub Actions. The user
subscribes to the raw file URL once in Google Calendar ("Add calendar → From URL");
new and updated events then flow in automatically.

Chosen over alternatives:

- **Google Calendar API direct sync** — rejected: requires a Google Cloud project,
  OAuth consent setup, and credential management for no real benefit here.
- **One-off .ics import** — rejected: manual re-imports create duplicates and
  leave stale events behind.

Implementation language: **Python, standard library only.** No dependencies means
the GitHub Actions workflow is trivial (checkout → run → commit) and the script
stays easy to read and maintain.

## Data source

`https://raw.githubusercontent.com/bigfoott/ScrapedDuck/data/events.min.json`

Each event object has: `eventID` (stable string), `name`, `eventType`, `heading`,
`link` (LeekDuck page), `image`, `start`/`end` (ISO 8601, nullable, mostly
timezone-less local times; some UTC with `Z` suffix), and `extraData`
(type-specific: spawns, bonuses, raid bosses, shinies, special research).

## Repo layout

```
PokemonCalendar/
├── generate_ics.py               # generator script (stdlib only)
├── config.json                   # included event types + feed name
├── events.ics                    # generated output, committed
├── tests/test_generate.py        # unit tests (stdlib unittest)
└── .github/workflows/update.yml  # scheduled regeneration
```

## Generator behavior

1. Fetch `events.min.json`.
2. Filter to events whose `eventType` is in the `config.json` allowlist.
   Initial allowlist (playable, time-boxed events; excludes season-long
   clutter like `go-battle-league`, `season`, `go-pass`):
   `community-day`, `raid-day`, `raid-hour`, `pokemon-spotlight-hour`,
   `max-mondays`, `research`, `raid-battles`, `elite-raids`,
   `pokemon-go-fest`, `event`, `choose-your-path`, `research-breakthrough`,
   `ticketed-event`, `location-specific`, `live-event`, `bonus-hour`,
   `go-tour`, `safari-zone`.
3. Skip events with a null `start`. If `end` is null, default to start + 1 hour.
4. Emit one VEVENT per event and write `events.ics`.

### Timezone handling

- Timezone-less datetimes (the common case — "2pm local time" events) become
  **floating** ICS times (no `TZID`, no `Z`). Google renders them in the
  calendar's own timezone, which matches Pokemon GO's local-time semantics.
- Datetimes with a `Z` suffix stay UTC (`...Z` in ICS).

### Deduplication / updates

`UID` is `<eventID>@scrapedduck`. Stable UIDs mean regeneration updates events
in place (no duplicates), and events dropped from the feed are removed from the
subscribed calendar. `DTSTAMP` and `SEQUENCE` handling: `DTSTAMP` is generation
time; no `SEQUENCE` tracking needed since Google re-reads the whole feed.

### Event content

- `SUMMARY`: event name.
- `DESCRIPTION`: event heading/type, then whatever `extraData` provides —
  featured spawns, raid bosses, bonuses, shiny availability (✨ marker) —
  followed by the LeekDuck link.
- `URL`: LeekDuck event page.

### ICS correctness details

- Escape `\`, `;`, `,`, and newlines in text values per RFC 5545.
- Fold lines longer than 75 octets (UTF-8 aware).
- CRLF line endings.
- `PRODID`/`VERSION`/`CALSCALE` headers; `X-WR-CALNAME` from config.

## Automation

GitHub Actions workflow (`update.yml`):

- Triggers: cron every 12 hours + `workflow_dispatch` (manual).
- Steps: checkout → run `generate_ics.py` → commit & push `events.ics` only if
  it changed.
- Failure mode: if ScrapedDuck is unreachable or returns garbage, the script
  exits non-zero, the workflow fails (GitHub notifies by email), and the last
  good committed `events.ics` keeps serving. The calendar goes stale rather
  than breaking.

## Error handling

- Network/HTTP failure: exit non-zero with a clear message.
- Individual malformed event (unparseable date, missing fields): skip that
  event, print a warning, continue.
- Empty result after filtering: still write a valid (possibly empty) calendar,
  but exit non-zero if the fetched feed itself was empty/unparseable —
  that indicates an upstream problem, not a quiet week.

## Testing

Stdlib `unittest`:

- Text escaping and 75-octet line folding.
- Floating vs UTC datetime formatting.
- Null `end` → +1 hour default; null `start` → skipped.
- Event-type filtering against the config allowlist.
- Description assembly from representative `extraData` shapes
  (community day, raid battles, spotlight hour, generic event).
- Live smoke test (network-marked): real feed fetches, parses, and yields a
  calendar with ≥1 event.

## One-time user setup (after implementation)

1. Create a GitHub repository and push this project.
2. Confirm the Actions workflow runs (or trigger it manually once).
3. Google Calendar → Settings → Add calendar → From URL → paste
   `https://raw.githubusercontent.com/<user>/<repo>/<branch>/events.ics`.
4. Note: Google refreshes subscribed calendars on its own schedule
   (commonly 12–48 h lag). Fine for events announced weeks in advance.
