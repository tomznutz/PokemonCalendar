import unittest
from datetime import datetime

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


if __name__ == "__main__":
    unittest.main()
