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
