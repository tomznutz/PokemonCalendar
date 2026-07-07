import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import generate_ics


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


class DatetimeTests(unittest.TestCase):
    def test_parse_local_datetime_is_floating(self):
        dt, is_utc = generate_ics.parse_dt("2026-07-04T14:00:00")
        self.assertEqual(dt, datetime(2026, 7, 4, 14, 0, 0))
        self.assertFalse(is_utc)

    def test_parse_utc_datetime(self):
        dt, is_utc = generate_ics.parse_dt("2026-07-04T14:00:00Z")
        self.assertEqual(dt, datetime(2026, 7, 4, 14, 0, 0))
        self.assertTrue(is_utc)

    def test_parse_offset_datetime_normalizes_to_utc(self):
        dt, is_utc = generate_ics.parse_dt("2026-07-04T16:30:00+02:30")
        self.assertEqual(dt, datetime(2026, 7, 4, 14, 0, 0))
        self.assertIsNone(dt.tzinfo)
        self.assertTrue(is_utc)

    def test_format_floating(self):
        dt = datetime(2026, 7, 4, 14, 0, 0)
        self.assertEqual(generate_ics.format_dt(dt, is_utc=False), "20260704T140000")

    def test_format_utc(self):
        dt = datetime(2026, 7, 4, 14, 0, 0)
        self.assertEqual(generate_ics.format_dt(dt, is_utc=True), "20260704T140000Z")


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

    def test_skips_event_with_unparseable_end(self):
        events = [make_event(end="not-a-date"), make_event(eventID="ok")]
        kept = generate_ics.filter_events(events, {"raid-hour"})
        self.assertEqual([e["eventID"] for e in kept], ["ok"])

    def test_skips_event_with_end_before_start(self):
        events = [
            make_event(start="2026-07-15T18:00:00", end="2026-07-14T19:00:00"),
            make_event(eventID="ok"),
        ]
        kept = generate_ics.filter_events(events, {"raid-hour"})
        self.assertEqual([e["eventID"] for e in kept], ["ok"])

    def test_skips_non_dict_entries(self):
        kept = generate_ics.filter_events(
            ["not-a-dict", None, make_event(eventID="ok")], {"raid-hour"}
        )
        self.assertEqual([e["eventID"] for e in kept], ["ok"])

    def test_skips_event_missing_id_or_name(self):
        no_id = make_event()
        del no_id["eventID"]
        no_name = make_event(name=None)
        kept = generate_ics.filter_events(
            [no_id, no_name, make_event(eventID="ok")], {"raid-hour"}
        )
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

    def test_tolerates_malformed_list_items(self):
        event = make_event(
            extraData={
                "communityday": {
                    "spawns": [{"image": "x"}, {"name": "Sobble", "image": "x"}],
                    "bonuses": [{"image": "x"}],
                    "shinies": [],
                },
                "raidbattles": {"bosses": [{"canBeShiny": True}], "shinies": []},
                "generic": {"hasSpawns": True, "hasFieldResearchTasks": False},
            }
        )
        desc = generate_ics.build_description(event)
        self.assertIn("Featured: Sobble", desc)
        self.assertNotIn("Bosses:", desc)
        self.assertNotIn("Bonuses:", desc)

    def test_tolerates_missing_extra_data(self):
        desc = generate_ics.build_description(make_event(extraData=None))
        self.assertIn("Raid Hour", desc)

    def test_tolerates_missing_link(self):
        desc = generate_ics.build_description(make_event(link=None))
        self.assertIn("Raid Hour", desc)


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

    def test_dtstamp_normalized_to_utc(self):
        est = timezone(timedelta(hours=-5))
        now = datetime(2026, 7, 5, 7, 0, 0, tzinfo=est)  # == 12:00 UTC
        lines = generate_ics.build_vevent(make_event(), now)
        self.assertIn("DTSTAMP:20260705T120000Z", lines)


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

    def test_fetch_failure_exits_with_clear_message(self):
        def failing_fetch():
            raise urllib.error.URLError("connection refused")
        with self.assertRaises(SystemExit) as ctx:
            generate_ics.main(fetch=failing_fetch, output_path=Path(tempfile.mkdtemp()) / "events.ics")
        self.assertIn("failed to fetch", str(ctx.exception))

    def test_non_list_feed_exits_nonzero(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run_main({"error": "not found"})
        self.assertIn("not a list", str(ctx.exception))


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


if __name__ == "__main__":
    unittest.main()
