#!/usr/bin/env python3
"""Regression tests for the pipeline. Run: python -m unittest discover tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from classify import classify_production
from dedup import canonical_key, deduplicate, merge_production, normalize, strip_attribution
from filters import not_a_production
from main import cleanup_state, send_notifications, sweep_deadlines

TODAY = "2026-09-21"


def item(title, **kw):
    base = {"title": title, "source": "cityofsydney", "status": "active"}
    base.update(kw)
    return base


def fresh_state():
    return {"productions": {}, "__dedup_index__": {}, "__notified__": {}}


class TestNormalize(unittest.TestCase):
    def test_punctuation_becomes_a_space(self):
        # Dropping the hyphen outright made these two different shows.
        self.assertEqual(normalize("All-Star Circus"), normalize("All Star Circus"))
        self.assertEqual(canonical_key("All-Star Circus"), canonical_key("All Star Circus"))

    def test_stop_words_and_order_ignored(self):
        self.assertEqual(canonical_key("The Boys Are Kissing"), canonical_key("Boys Kissing Are"))

    def test_distinct_titles_stay_distinct(self):
        self.assertNotEqual(canonical_key("The Nutcracker"), canonical_key("The Nutcracker on Ice"))


class TestStripAttribution(unittest.TestCase):
    def test_possessive_prefix(self):
        self.assertEqual(strip_attribution("Noel Coward's Private Lives"), "Private Lives")

    def test_trailing_by_author(self):
        self.assertEqual(strip_attribution("The Boys Are Kissing by Zak Zarafshan"), "The Boys Are Kissing")

    def test_company_presents(self):
        self.assertEqual(
            canonical_key("Pinchgut Opera presents Coffee and a Dead Canary"),
            canonical_key("Pinchgut Opera's Coffee and a Dead Canary"),
        )

    def test_presents_inside_a_title_is_left_alone(self):
        self.assertEqual(strip_attribution("Christmas Presents for All"), "Christmas Presents for All")

    def test_strips_the_author_from_a_normal_title(self):
        self.assertEqual(strip_attribution("Cats by Andrew Lloyd Webber"), "Cats")

    def test_never_strips_a_title_down_to_nothing(self):
        # Stripping would leave "M", so keep the original.
        self.assertEqual(strip_attribution("M by Anton Chekhov"), "M by Anton Chekhov")


class TestFilters(unittest.TestCase):
    def test_classes_and_workshops_are_not_productions(self):
        for title in [
            "Ballet class: Little Ballet 3-5 years (Pyrmont)",
            "Jazz class 3-8 years (Pyrmont)",
            "Movement and dance class",
            "Free Salsa Classes in Surry Hills",
            "Sketch Writing Course for Beginners",
            "Drawing with a Drag Queen workshop",
            "The ultimate Sydney stand-up comedy school experience",
            "Sydney Harbour Retro Boat Party",
        ]:
            self.assertTrue(not_a_production(title), title)

    def test_real_shows_survive(self):
        for title in [
            "Play School Live Concert 2026: Humpty's Big Celebration!",
            "A Night at the Library",
            "The Shakesbeer Sessions: A Midsummer Night's Dream",
            "Hamilton",
            "Cabaret",
        ]:
            self.assertIsNone(not_a_production(title), title)


class TestDedup(unittest.TestCase):
    def test_new_then_existing(self):
        state = fresh_state()
        status, pid = deduplicate(item("Vanya", start_date="2026-10-01", end_date="2026-11-01"), state, today=TODAY)
        self.assertEqual(status, "new")
        status2, pid2 = deduplicate(item("Vanya", start_date="2026-10-01", end_date="2026-11-01"), state, today=TODAY)
        self.assertEqual((status2, pid2), ("existing", pid))
        self.assertEqual(len(state["productions"]), 1)

    def test_untitled_is_skipped(self):
        state = fresh_state()
        self.assertEqual(deduplicate(item(""), state, today=TODAY), ("skip", None))
        self.assertEqual(state["productions"], {})

    def test_dangling_index_entry_rebuilds_the_record(self):
        # A stale __dedup_index__ pointing at a deleted production used to
        # create an entry with no id and no title.
        state = fresh_state()
        _, pid = deduplicate(item("Vanya", start_date="2026-10-01", end_date="2026-11-01"), state, today=TODAY)
        del state["productions"][pid]
        status, pid2 = deduplicate(item("Vanya", start_date="2026-10-01", end_date="2026-11-01"), state, today=TODAY)
        self.assertEqual(status, "new")
        self.assertEqual(state["productions"][pid2]["title"], "Vanya")
        self.assertEqual(state["productions"][pid2]["id"], pid2)


class TestMerge(unittest.TestCase):
    def test_extended_run_is_picked_up_and_reopens_the_show(self):
        existing = {"id": "x", "title": "Vanya", "status": "closed",
                    "start_date": "2026-01-01", "end_date": "2026-02-01"}
        merged = merge_production(existing, {"end_date": "2026-12-01"}, today=TODAY)
        self.assertEqual(merged["end_date"], "2026-12-01")
        self.assertEqual(merged["status"], "active")

    def test_finished_run_closes(self):
        existing = {"id": "x", "title": "Vanya", "status": "active", "end_date": "2026-09-01"}
        self.assertEqual(merge_production(existing, {}, today=TODAY)["status"], "closed")

    def test_needs_review_upgrades_once_dates_arrive(self):
        existing = {"id": "x", "title": "Vanya", "status": "needs_review"}
        merged = merge_production(existing, {"start_date": "2026-10-01", "end_date": "2026-11-01"}, today=TODAY)
        self.assertEqual(merged["status"], "active")

    def test_suppression_is_never_undone(self):
        existing = {"id": "x", "title": "Salsa class", "status": "suppressed", "end_date": "2027-01-01"}
        self.assertEqual(merge_production(existing, {}, today=TODAY)["status"], "suppressed")

    def test_keeps_the_lowest_price(self):
        existing = {"id": "x", "title": "V", "status": "active", "price_from": 80}
        self.assertEqual(merge_production(existing, {"price_from": 45}, today=TODAY)["price_from"], 45)
        self.assertEqual(merge_production(existing, {"price_from": 90}, today=TODAY)["price_from"], 45)

    def test_todaytix_booking_url_wins(self):
        existing = {"id": "x", "title": "V", "status": "active", "booking_url": "https://whatson/e"}
        merged = merge_production(existing, {"source": "todaytix", "booking_url": "https://todaytix/x"}, today=TODAY)
        self.assertEqual(merged["booking_url"], "https://todaytix/x")

    def test_curated_fields_are_not_clobbered(self):
        existing = {"id": "x", "title": "V", "status": "active", "suburb": "Surry Hills"}
        self.assertEqual(merge_production(existing, {"suburb": "Sydney"}, today=TODAY)["suburb"], "Surry Hills")


class TestSweep(unittest.TestCase):
    def test_closes_finished_and_reports_closing_today(self):
        state = fresh_state()
        state["productions"] = {
            "a": {"id": "a", "title": "Done", "status": "active", "end_date": "2026-09-20"},
            "b": {"id": "b", "title": "Last night", "status": "active", "end_date": TODAY},
            "c": {"id": "c", "title": "Running", "status": "active", "end_date": "2026-12-01"},
            "d": {"id": "d", "title": "Open ended", "status": "active", "end_date": ""},
        }
        closing = sweep_deadlines(state, TODAY)
        self.assertEqual(state["productions"]["a"]["status"], "closed")
        self.assertEqual(state["productions"]["c"]["status"], "active")
        self.assertEqual(state["productions"]["d"]["status"], "active")
        self.assertEqual([p["id"] for p in closing], ["b"])


class TestCleanup(unittest.TestCase):
    def test_suppresses_junk_already_in_state(self):
        state = fresh_state()
        state["productions"] = {
            "a": {"id": "a", "title": "Free Salsa Classes in Surry Hills", "status": "active", "genre": "dance"},
            "b": {"id": "b", "title": "Hamilton", "status": "active", "genre": "musical"},
        }
        cleanup_state(state)
        self.assertEqual(state["productions"]["a"]["status"], "suppressed")
        self.assertEqual(state["productions"]["b"]["status"], "active")

    def test_film_genre_is_reclassified(self):
        state = fresh_state()
        state["productions"] = {
            "a": {"id": "a", "title": "Belvoir: The Seagull", "status": "active", "genre": "film",
                  "venue": "Belvoir St Theatre", "snippet": "A new play"},
        }
        cleanup_state(state)
        self.assertNotEqual(state["productions"]["a"]["genre"], "film")


class TestNotifyOnce(unittest.TestCase):
    def test_a_rerun_on_the_same_day_does_not_re_announce(self):
        state = fresh_state()
        state["productions"] = {
            "a": {"id": "a", "title": "Opens today", "status": "active",
                  "start_date": TODAY, "end_date": "2026-12-01"},
        }
        sent = []
        import notify
        original = notify.send_embed
        notify.send_embed = lambda embed: sent.append(embed["title"]) or True
        try:
            send_notifications(state, ["a"], [], TODAY)
            first = len(sent)
            send_notifications(state, ["a"], [], TODAY)
            self.assertEqual(len(sent), first, "second run re-sent notifications")
            self.assertEqual(first, 2)  # one "new", one "opening tonight"
        finally:
            notify.send_embed = original

    def test_suppressed_productions_are_not_announced(self):
        state = fresh_state()
        state["productions"] = {"a": {"id": "a", "title": "Salsa class", "status": "suppressed"}}
        sent = []
        import notify
        original = notify.send_embed
        notify.send_embed = lambda embed: sent.append(embed) or True
        try:
            send_notifications(state, ["a"], [], TODAY)
            self.assertEqual(sent, [])
        finally:
            notify.send_embed = original


class TestClassify(unittest.TestCase):
    def test_opera_house_is_not_an_opera(self):
        self.assertNotEqual(
            classify_production({"title": "The Seagull", "venue": "Sydney Opera House", "snippet": ""}),
            "opera",
        )

    def test_existing_genre_is_kept(self):
        self.assertEqual(classify_production({"title": "Whatever", "genre": "cabaret"}), "cabaret")


if __name__ == "__main__":
    unittest.main()
