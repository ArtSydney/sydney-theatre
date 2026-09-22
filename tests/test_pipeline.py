#!/usr/bin/env python3
"""Regression tests for the pipeline. Run: python -m unittest discover tests"""

import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from classify import classify_production
from dedup import (canonical_key, consolidate, dedup_candidates, deduplicate,
                   discriminating_difference, is_same_production, merge_production,
                   normalize, record_sighting, reindex, strip_attribution,
                   same_engagement, title_similarity, venue_root)
from fetch import extract_season_rows, parse_riverside_dates, parse_spektrix_event
from filters import not_a_production
from main import STALE_AFTER_DAYS, cleanup_state, send_notifications, sweep_deadlines

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


def show(title, venue="", suburb="", start="", end=""):
    return {"title": title, "venue_id": venue, "suburb": suburb,
            "start_date": start, "end_date": end}


class TestSecondStageMatching(unittest.TestCase):
    """Every case here came out of an audit of the real data."""

    def assertMerges(self, a, b, why):
        ok, reason = is_same_production(a, b)
        self.assertTrue(ok, f"should merge ({why}): {reason}")

    def assertSeparate(self, a, b, why):
        ok, reason = is_same_production(a, b)
        self.assertFalse(ok, f"should NOT merge ({why}): {reason}")

    def test_company_prefix_across_sources(self):
        # The duplicate this whole stage exists for: TodayTix filed it under
        # the room, City of Sydney under the building and with the company
        # name in front.
        self.assertMerges(
            show("Copland Dance Episodes", "joan-sutherland-theatre", "", "2026-11-06", "2026-11-21"),
            show("The Australian Ballet: Copland Dance Episodes", "sydney-opera-house", "", "2026-11-06", "2026-11-22"),
            "same show, room vs building")

    def test_ampersand_and_author(self):
        self.assertMerges(
            show("Dixon & Daughters", "old-fitz-theatre", "", "2026-09-18", "2026-10-03"),
            show("Dixon and Daughters by Deborah Bruce", "old-fitz-theatre", "", "2026-09-18", "2026-10-03"),
            "& vs and, plus author")

    # --- things that must never merge -----------------------------------

    def test_qualified_title_is_a_different_show(self):
        self.assertSeparate(
            show("The Nutcracker on Ice", "coliseum-theatre", "", "2026-12-10", "2026-12-20"),
            show("The Nutcracker", "joan-sutherland-theatre", "", "2026-11-28", "2026-12-16"),
            "on Ice is a different production")

    def test_short_title_is_not_swallowed_by_a_longer_one(self):
        for other in ("The Man From Snowy River in Concert", "The Choir of Man"):
            self.assertSeparate(
                show(other, "coliseum-theatre", "", "2026-10-10", "2026-10-10"),
                show("The Man", "old-fitz-theatre", "", "2026-09-21", "2026-10-02"),
                "containment is not identity")

    def test_different_weeknights_at_one_venue(self):
        self.assertSeparate(
            show("The Comedy Store Friday Showcase", "comedy-store", "Moore Park", "2026-10-01", "2026-12-01"),
            show("The Comedy Store Saturday Showcase", "comedy-store", "Moore Park", "2026-10-01", "2026-12-01"),
            "Friday is not Saturday")

    def test_touring_show_at_different_venues(self):
        self.assertSeparate(
            show("The Shakesbeer Sessions: A Midsummer Night's Dream @The Oaks", "", "Neutral Bay", "2026-10-25", "2026-11-08"),
            show("The Shakesbeer Sessions: A Midsummer Night's Dream Annandale", "", "Annandale", "2026-10-16", "2026-11-06"),
            "same production, separate engagements")

    def test_same_title_different_venue(self):
        self.assertSeparate(
            show("Macbeth", "bell-shakespeare", "", "2026-09-24", "2026-10-10"),
            show("Macbeth", "the-pavilion", "", "2027-03-01", "2027-03-05"),
            "venue disagreement is decisive")

    def test_overlapping_dates_alone_never_merge(self):
        self.assertSeparate(
            show("Wolf by Circa", "old-fitz-theatre", "", "2026-10-21", "2026-10-21"),
            show("Wolf by Circa", "the-pavilion", "", "2026-10-21", "2026-10-21"),
            "concurrent runs are not evidence")

    def test_numbered_and_junior_editions(self):
        self.assertSeparate(
            show("Cabaret Season 1", "hayes-theatre", "", "2026-10-01", "2026-10-20"),
            show("Cabaret Season 2", "hayes-theatre", "", "2026-10-05", "2026-10-25"), "numbered")
        self.assertSeparate(
            show("Bluey's Big Play Junior", "capitol-theatre", "", "2026-10-01", "2026-10-20"),
            show("Bluey's Big Play", "capitol-theatre", "", "2026-10-01", "2026-10-20"), "junior edition")


class TestSeparateEngagements(unittest.TestCase):
    """A touring show keeps its title from venue to venue."""

    def test_same_title_different_venue_is_a_different_engagement(self):
        # Bell Shakespeare's Macbeth plays the Opera House in November and
        # the Pavilion in September. Both normalise to "macbeth", so the
        # exact key alone swallowed the second date.
        a = {"title": "Macbeth", "venue_id": "playhouse", "venue": "The Playhouse",
             "start_date": "2026-11-18", "end_date": "2026-12-06"}
        b = {"title": "Bell Shakespeare's 'Macbeth'", "venue_id": "the-pavilion",
             "venue": "The Pavilion Performing Arts Centre",
             "start_date": "2026-09-24", "end_date": "2026-09-24"}
        self.assertFalse(same_engagement(a, b))

    def test_one_run_named_two_ways_is_still_one_engagement(self):
        a = {"title": "We Are The Tigers", "venue_id": "hayes-theatre",
             "venue": "Hayes Theatre Co", "start_date": "2026-10-09", "end_date": "2026-11-08"}
        b = {"title": "We Are The Tigers", "venue_id": "hayes-theatre",
             "venue": "Hayes Theatre", "start_date": "2026-10-09", "end_date": "2026-11-08"}
        self.assertTrue(same_engagement(a, b))

    def test_a_room_and_its_building_are_one_engagement(self):
        a = {"title": "Copland Dance Episodes", "venue_id": "joan-sutherland-theatre",
             "venue": "Joan Sutherland Theatre | Sydney Opera House",
             "start_date": "2026-11-06", "end_date": "2026-11-21"}
        b = {"title": "Copland Dance Episodes", "venue_id": "sydney-opera-house",
             "venue": "Sydney Opera House", "start_date": "2026-11-06", "end_date": "2026-11-22"}
        self.assertTrue(same_engagement(a, b))

    def test_unmatched_venues_with_disjoint_runs_are_separate(self):
        # Neither side matched a venue record, so only the venue wording and
        # the dates can tell them apart.
        a = {"title": "Wolf", "venue_id": "", "venue": "Q Theatre | The Joan, Penrith",
             "start_date": "2026-10-07", "end_date": "2026-10-08"}
        b = {"title": "Wolf", "venue_id": "", "venue": "The Pavilion Performing Arts Centre",
             "start_date": "2026-10-21", "end_date": "2026-10-21"}
        self.assertFalse(same_engagement(a, b))

    def test_generic_venue_words_do_not_prove_a_match(self):
        # "the", "theatre" and "sydney" appear in half the venue names in
        # town; matching on them merged unrelated engagements.
        a = {"title": "X", "venue": "The Sydney Theatre", "start_date": "2026-01-01",
             "end_date": "2026-01-02"}
        b = {"title": "X", "venue": "The Theatre Sydney Centre", "start_date": "2026-06-01",
             "end_date": "2026-06-02"}
        self.assertFalse(same_engagement(a, b))


class TestOneNightEvents(unittest.TestCase):
    def test_a_listing_with_no_end_date_closes_the_day_after(self):
        state = fresh_state()
        deduplicate(item("A Reading", start_date="2026-09-21", end_date=""),
                    state, today="2026-09-21")
        prod = next(iter(state["productions"].values()))
        self.assertEqual(prod["end_date"], "2026-09-21",
                         "no further date means the run ended that night")
        sweep_deadlines(state, "2026-09-22")
        self.assertEqual(prod["status"], "closed")

    def test_a_real_end_date_still_wins_later(self):
        state = fresh_state()
        _, pid = deduplicate(item("Extended", start_date="2026-09-21", end_date=""),
                             state, today="2026-09-21")
        deduplicate(item("Extended", start_date="2026-09-21", end_date="2026-12-01"),
                    state, today="2026-09-21")
        self.assertEqual(state["productions"][pid]["end_date"], "2026-12-01")


class TestVenueFamilies(unittest.TestCase):
    def test_a_room_resolves_to_its_building(self):
        self.assertEqual(venue_root("drama-theatre"), "sydney-opera-house")
        self.assertEqual(venue_root("sydney-opera-house"), "sydney-opera-house")

    def test_an_unknown_venue_is_its_own_root(self):
        self.assertEqual(venue_root("not-a-venue"), "not-a-venue")
        self.assertEqual(venue_root(""), "")


class TestDiscriminators(unittest.TestCase):
    def test_weekday_difference_separates(self):
        self.assertTrue(discriminating_difference("Comedy Friday", "Comedy Saturday"))

    def test_company_prefix_does_not_separate(self):
        self.assertFalse(discriminating_difference(
            "The Australian Ballet: Copland Dance Episodes", "Copland Dance Episodes"))


class TestSightings(unittest.TestCase):
    def test_each_source_is_kept_once(self):
        prod = {"title": "X"}
        record_sighting(prod, {"source": "todaytix", "title": "X", "source_url": "u1"})
        record_sighting(prod, {"source": "cityofsydney", "title": "X the Musical"})
        record_sighting(prod, {"source": "todaytix", "title": "X", "source_url": "u2"})
        self.assertEqual(len(prod["sightings"]), 2)
        tt = [s for s in prod["sightings"] if s["source"] == "todaytix"][0]
        self.assertEqual(tt["url"], "u2", "a later sighting replaces the earlier one")


class TestConsolidate(unittest.TestCase):
    def test_merges_an_existing_duplicate_and_is_idempotent(self):
        state = fresh_state()
        state["productions"] = {
            "a": {"id": "a", "title": "Copland Dance Episodes", "status": "active",
                  "venue_id": "drama-theatre", "start_date": "2026-11-06",
                  "end_date": "2026-11-21", "fetched_at": "2026-09-01"},
            "b": {"id": "b", "title": "The Australian Ballet: Copland Dance Episodes",
                  "status": "active", "venue_id": "sydney-opera-house",
                  "start_date": "2026-11-06", "end_date": "2026-11-22",
                  "fetched_at": "2026-09-02"},
        }
        self.assertEqual(consolidate(state, TODAY), 1)
        self.assertEqual(len(state["productions"]), 1)
        self.assertEqual(consolidate(state, TODAY), 0)

    def test_leaves_distinct_shows_alone(self):
        state = fresh_state()
        state["productions"] = {
            "a": {"id": "a", "title": "The Nutcracker", "status": "active",
                  "venue_id": "joan-sutherland-theatre", "start_date": "2026-11-28",
                  "end_date": "2026-12-16", "fetched_at": "2026-09-01"},
            "b": {"id": "b", "title": "The Nutcracker on Ice", "status": "active",
                  "venue_id": "coliseum-theatre", "start_date": "2026-12-10",
                  "end_date": "2026-12-20", "fetched_at": "2026-09-02"},
        }
        self.assertEqual(consolidate(state, TODAY), 0)
        self.assertEqual(len(state["productions"]), 2)


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


class TestOpenEndedRuns(unittest.TestCase):
    """A run with no end date used to stay active forever."""

    def state_with(self, **prod):
        base = {"id": "a", "title": "Open ended", "status": "active", "end_date": ""}
        base.update(prod)
        return {"productions": {"a": base}, "__dedup_index__": {}, "__notified__": {}}

    def test_unstamped_run_gets_a_clock_rather_than_closing(self):
        state = self.state_with()
        sweep_deadlines(state, TODAY)
        self.assertEqual(state["productions"]["a"]["status"], "active")
        self.assertEqual(state["productions"]["a"]["last_seen"], TODAY)

    def test_still_listed_run_stays_open(self):
        state = self.state_with(last_seen=TODAY)
        sweep_deadlines(state, TODAY)
        self.assertEqual(state["productions"]["a"]["status"], "active")

    def test_run_unlisted_past_the_cutoff_closes(self):
        stale = (date.fromisoformat(TODAY) - timedelta(days=STALE_AFTER_DAYS + 1)).isoformat()
        state = self.state_with(last_seen=stale)
        sweep_deadlines(state, TODAY)
        self.assertEqual(state["productions"]["a"]["status"], "closed")

    def test_just_inside_the_cutoff_stays_open(self):
        fresh = (date.fromisoformat(TODAY) - timedelta(days=STALE_AFTER_DAYS - 1)).isoformat()
        state = self.state_with(last_seen=fresh)
        sweep_deadlines(state, TODAY)
        self.assertEqual(state["productions"]["a"]["status"], "active")

    def test_a_broken_fetch_does_not_age_anything_out(self):
        stale = (date.fromisoformat(TODAY) - timedelta(days=STALE_AFTER_DAYS + 30)).isoformat()
        state = self.state_with(last_seen=stale)
        sweep_deadlines(state, TODAY, close_stale=False)
        self.assertEqual(state["productions"]["a"]["status"], "active")

    def test_a_dated_run_is_unaffected_by_staleness(self):
        stale = (date.fromisoformat(TODAY) - timedelta(days=STALE_AFTER_DAYS + 5)).isoformat()
        state = self.state_with(end_date="2026-12-01", last_seen=stale)
        sweep_deadlines(state, TODAY)
        self.assertEqual(state["productions"]["a"]["status"], "active")


class TestLastSeen(unittest.TestCase):
    def test_dedup_stamps_last_seen_on_new_and_existing(self):
        state = fresh_state()
        _, pid = deduplicate(item("Vanya", start_date="2026-10-01", end_date="2026-11-01"),
                             state, today="2026-09-01")
        self.assertEqual(state["productions"][pid]["last_seen"], "2026-09-01")
        deduplicate(item("Vanya", start_date="2026-10-01", end_date="2026-11-01"),
                    state, today=TODAY)
        self.assertEqual(state["productions"][pid]["last_seen"], TODAY)


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


class TestRiversideDates(unittest.TestCase):
    """Every format below is one the venue's page actually uses."""

    def check(self, text, start, end):
        self.assertEqual(parse_riverside_dates(text, 2026), (start, end), text)

    def test_same_month_range(self):
        self.check("23 - 27 September 2026", "2026-09-23", "2026-09-27")

    def test_single_date_with_weekday(self):
        self.check("Wednesday 23 September 2026", "2026-09-23", "2026-09-23")

    def test_cross_month_range(self):
        self.check("26 November - 5 December 2026", "2026-11-26", "2026-12-05")

    def test_time_suffixes_are_ignored(self):
        self.check("Friday 30 October, 7:30pm", "2026-10-30", "2026-10-30")
        self.check("Sunday 15 November 2026 at 10:30am", "2026-11-15", "2026-11-15")

    def test_range_crossing_new_year(self):
        self.check("30 December - 4 January 2026", "2026-12-30", "2027-01-04")

    def test_unparseable_text_is_refused_rather_than_guessed(self):
        self.check("Coming soon", "", "")
        self.check("", "", "")


class TestCompanySeasonRows(unittest.TestCase):
    PAGE = """
    <div><h3>My Fair Lady</h3><p>Sydney Opera House,</p><p>22 September-31 October</p></div>
    <div><h3>Aida on Sydney Harbour</h3><p>Mrs Macquaries Point</p><p>27 March-25 April</p></div>
    <div><h3>Desandre &amp; Dunford</h3><p>City Recital Hall</p><p>18 October</p></div>
    """

    def test_reads_title_venue_and_dates(self):
        rows = extract_season_rows(self.PAGE)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], ("My Fair Lady", "Sydney Opera House", "22 September-31 October"))
        self.assertEqual(rows[1][1], "Mrs Macquaries Point")

    def test_entities_are_decoded(self):
        self.assertEqual(extract_season_rows(self.PAGE)[2][0], "Desandre & Dunford")

    def test_a_page_without_listings_yields_nothing(self):
        self.assertEqual(extract_season_rows("<div><p>Coming soon</p></div>"), [])


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
