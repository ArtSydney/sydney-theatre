#!/usr/bin/env python3
"""Regression tests for the pipeline. Run: python -m unittest discover tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from classify import classify_production
from dedup import canonical_key, deduplicate, merge_production, normalize, reindex, strip_attribution
from fetch import parse_spektrix_event
from filters import not_a_production
from main import cleanup_state, send_notifications, sweep_deadlines

TODAY = "2026-09-21"


def item(title, **kw):
    base = {"title": title, "source": "cityofsydney", "status": "active"}
    base.update(kw)
    return base


def fresh_state():
    return {"productions": {}, "__dedup_index__": {}, "__notified__": {}}


def json_copy(obj):
    import json
    return json.loads(json.dumps(obj, sort_keys=True))


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

    def test_junk_categories_catch_what_titles_miss(self):
        # A book club and an artist talk look like ordinary titles; the
        # source's own category is what gives them away.
        self.assertTrue(not_a_production("The Line of Beauty by Alan Hollinghurst",
                                         ["theatre-dance-and-film", "talks-courses-and-workshops"]))
        self.assertTrue(not_a_production("Ignite Talks Sydney 2026",
                                         ["talks-courses-and-workshops"]))
        self.assertTrue(not_a_production("David Hockney: Bigger & Closer", ["exhibitions"]))

    def test_tours_category_is_not_treated_as_junk(self):
        # The source files Disney's The Lion King under tours-and-experiences.
        self.assertIsNone(not_a_production("Disney's The Lion King",
                                           ["theatre-dance-and-film", "tours-and-experiences"]))

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


class TestReindex(unittest.TestCase):
    def test_collapses_records_orphaned_by_a_key_change(self):
        # Two records for one show, ids from two different key rules.
        state = fresh_state()
        state["productions"] = {
            "oldkey": {"id": "oldkey", "title": "All-Star Circus", "status": "active",
                       "fetched_at": "2026-08-23", "start_date": "2026-08-01",
                       "end_date": "2026-10-01", "venue": "Big Top"},
            "newkey": {"id": "newkey", "title": "All Star Circus", "status": "active",
                       "fetched_at": "2026-09-21", "start_date": "2026-08-01",
                       "end_date": "2026-12-01", "venue": "Big Top"},
        }
        state["__dedup_index__"] = {"oldkey": "oldkey", "newkey": "newkey"}
        reindex(state, today=TODAY)

        self.assertEqual(len(state["productions"]), 1)
        survivor = next(iter(state["productions"].values()))
        # The newer record's extended end date wins.
        self.assertEqual(survivor["end_date"], "2026-12-01")
        # id, key and index agree again.
        key = canonical_key("All Star Circus")
        self.assertEqual(survivor["id"], key)
        self.assertEqual(state["__dedup_index__"], {key: key})

    def test_is_idempotent(self):
        state = fresh_state()
        state["productions"] = {
            "a": {"id": "a", "title": "Vanya", "status": "active", "fetched_at": "2026-09-01"},
        }
        reindex(state, today=TODAY)
        first = json_copy(state)
        reindex(state, today=TODAY)
        self.assertEqual(json_copy(state), first)

    def test_suppression_survives_a_merge(self):
        state = fresh_state()
        state["productions"] = {
            "old": {"id": "old", "title": "Free Salsa Classes", "status": "suppressed",
                    "fetched_at": "2026-08-01"},
            "new": {"id": "new", "title": "Free Salsa Classes", "status": "active",
                    "fetched_at": "2026-09-01", "end_date": "2027-01-01"},
        }
        reindex(state, today=TODAY)
        self.assertEqual(len(state["productions"]), 1)
        self.assertEqual(next(iter(state["productions"].values()))["status"], "suppressed")

    def test_a_fetch_after_reindex_finds_the_existing_record(self):
        state = fresh_state()
        state["productions"] = {
            "oldkey": {"id": "oldkey", "title": "All-Star Circus", "status": "active",
                       "fetched_at": "2026-08-23", "start_date": "2026-08-01",
                       "end_date": "2026-10-01"},
        }
        state["__dedup_index__"] = {"oldkey": "oldkey"}
        reindex(state, today=TODAY)
        status, _ = deduplicate(item("All Star Circus", start_date="2026-08-01",
                                     end_date="2026-10-01"), state, today=TODAY)
        self.assertEqual(status, "existing")
        self.assertEqual(len(state["productions"]), 1)


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

    def test_stored_categories_are_re_filtered(self):
        # These records predate category filtering, so only a stored category
        # can retire them.
        state = fresh_state()
        state["productions"] = {
            "a": {"id": "a", "title": "Villa Coco by Andrew Sean Greer", "status": "active",
                  "genre": "play", "categories": ["talks-courses-and-workshops"]},
            "b": {"id": "b", "title": "Vanya", "status": "active", "genre": "play",
                  "categories": ["theatre-dance-and-film"]},
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


class TestSpektrixFeed(unittest.TestCase):
    VENUE = {"id": "old-fitz-theatre", "name": "Old Fitz Theatre", "suburb": "Woolloomooloo",
             "website": "https://www.oldfitztheatre.com.au"}
    FEED = {"type": "spektrix", "client": "oldfitztheatre",
            "booking_url": "https://purchase.oldfitztheatre.com.au/EventAvailability?EventId={web_id}"}

    def parse(self, **kw):
        event = {"name": "Catch As Catch Can", "id": "1601APDLXXQ",
                 "firstInstanceDateTime": "2026-10-09T19:30:00",
                 "lastInstanceDateTime": "2026-10-31T17:00:00",
                 "attribute_Type": "Mainstage", "description": "A play."}
        event.update(kw)
        return parse_spektrix_event(event, self.VENUE, self.FEED)

    def test_maps_the_fields_the_pipeline_needs(self):
        p = self.parse()
        self.assertEqual(p["title"], "Catch As Catch Can")
        self.assertEqual(p["start_date"], "2026-10-09")
        self.assertEqual(p["end_date"], "2026-10-31")
        self.assertEqual(p["venue_id"], "old-fitz-theatre")
        self.assertEqual(p["suburb"], "Woolloomooloo")
        self.assertEqual(p["genre"], "play")
        self.assertEqual(p["source"], "venue-feed")

    def test_booking_url_uses_the_numeric_web_id(self):
        # The event id carries the web id the box office expects:
        # "1601APDLXXQ" -> EventAvailability?EventId=1601
        self.assertEqual(
            self.parse()["booking_url"],
            "https://purchase.oldfitztheatre.com.au/EventAvailability?EventId=1601",
        )

    def test_programming_strand_is_stripped_from_the_title(self):
        # Otherwise "LATE NIGHT: The Man" never matches the same show
        # listed elsewhere as "The Man".
        self.assertEqual(self.parse(name="LATE NIGHT: The Man")["title"], "The Man")
        self.assertEqual(self.parse(name="READING: Prey by David Cole")["title"], "Prey by David Cole")
        self.assertEqual(self.parse(name="ONE-OFF: Green Scenes")["title"], "Green Scenes")

    def test_a_title_that_is_only_a_strand_is_left_alone(self):
        self.assertEqual(self.parse(name="Reading: Ab")["title"], "Reading: Ab")

    def test_junk_is_filtered_like_any_other_source(self):
        self.assertIsNone(self.parse(name="Improv class for beginners"))

    def test_missing_dates_fall_back_to_needs_review(self):
        p = self.parse(firstInstanceDateTime=None, lastInstanceDateTime=None)
        self.assertEqual(p["status"], "needs_review")

    def test_unnamed_event_is_skipped(self):
        self.assertIsNone(self.parse(name=""))


class TestBookingUrlPreference(unittest.TestCase):
    def test_venue_box_office_beats_an_aggregator_page(self):
        existing = {"id": "x", "title": "V", "status": "active",
                    "booking_url": "https://whatson.cityofsydney.nsw.gov.au/events/v",
                    "booking_source": "cityofsydney"}
        merged = merge_production(existing, {"source": "venue-feed",
                                             "booking_url": "https://box.office/e/1"}, today=TODAY)
        self.assertEqual(merged["booking_url"], "https://box.office/e/1")

    def test_aggregator_does_not_overwrite_the_box_office(self):
        existing = {"id": "x", "title": "V", "status": "active",
                    "booking_url": "https://box.office/e/1", "booking_source": "venue-feed"}
        merged = merge_production(existing, {"source": "cityofsydney",
                                             "booking_url": "https://whatson/e"}, today=TODAY)
        self.assertEqual(merged["booking_url"], "https://box.office/e/1")


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
