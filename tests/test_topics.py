"""Unit tests for topic_matcher.py. Run: python -m unittest discover -s tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import topic_matcher as tm  # noqa: E402


class MatchesTest(unittest.TestCase):

    def test_exact(self):
        self.assertTrue(tm.matches("brgy.jaro.purok-1.fire", "brgy.jaro.purok-1.fire"))
        self.assertFalse(tm.matches("brgy.jaro.purok-1.fire", "brgy.jaro.purok-1.flood"))
        self.assertFalse(tm.matches("brgy.jaro.purok-1", "brgy.jaro.purok-1.fire"))
        self.assertFalse(tm.matches("brgy.jaro.purok-1.fire", "brgy.jaro.purok-1"))

    def test_star_matches_exactly_one_level(self):
        self.assertTrue(tm.matches("brgy.jaro.*.fire", "brgy.jaro.purok-1.fire"))
        self.assertTrue(tm.matches("brgy.*.*.*", "brgy.molo.purok-2.noise"))
        self.assertTrue(tm.matches("report.*.status", "report.ab12cd34.status"))
        self.assertFalse(tm.matches("brgy.jaro.*", "brgy.jaro.purok-1.fire"))
        self.assertFalse(tm.matches("brgy.jaro.*.fire", "brgy.jaro.fire"))
        self.assertFalse(tm.matches("brgy.*.*.fire", "brgy.jaro.purok-1.flood"))

    def test_hash_matches_zero_or_more_levels(self):
        self.assertTrue(tm.matches("brgy.jaro.#", "brgy.jaro.purok-1.fire"))
        self.assertTrue(tm.matches("brgy.jaro.#", "brgy.jaro.advisory"))
        self.assertTrue(tm.matches("brgy.jaro.#", "brgy.jaro"))  # zero levels
        self.assertTrue(tm.matches("#", "city.iloilo.escalated.jaro"))
        self.assertTrue(tm.matches("city.iloilo.escalated.#", "city.iloilo.escalated.jaro"))
        self.assertFalse(tm.matches("brgy.jaro.#", "brgy.molo.purok-1.fire"))
        self.assertFalse(tm.matches("brgy.jaro.#", "city.iloilo.escalated.jaro"))

    def test_star_and_hash_together(self):
        self.assertTrue(tm.matches("brgy.*.#", "brgy.jaro.purok-1.fire"))
        self.assertTrue(tm.matches("brgy.*.#", "brgy.jaro"))
        self.assertFalse(tm.matches("brgy.*.#", "brgy"))

    def test_hash_not_last_never_matches(self):
        self.assertFalse(tm.matches("brgy.#.fire", "brgy.jaro.purok-1.fire"))

    def test_wildcard_is_whole_level_only(self):
        self.assertFalse(tm.matches("brgy.ja*.purok-1.fire", "brgy.jaro.purok-1.fire"))

    def test_any_match(self):
        pats = ["brgy.molo.#", "report.*.status"]
        self.assertTrue(tm.any_match(pats, "report.ab12cd34.status"))
        self.assertFalse(tm.any_match(pats, "brgy.jaro.purok-1.fire"))
        self.assertFalse(tm.any_match([], "brgy.jaro.purok-1.fire"))


class PatternValidationTest(unittest.TestCase):

    def test_valid_patterns(self):
        for p in ["brgy.jaro.*.fire", "brgy.jaro.#", "#", "*", "report.*.status",
                  "city.iloilo.escalated.#", "brgy.jaro.purok-1.fire"]:
            self.assertTrue(tm.is_valid_pattern(p), p)

    def test_invalid_patterns(self):
        for p in ["", "brgy.#.fire", "brgy..fire", ".brgy", "brgy.", "brgy.ja*",
                  "brgy.jaro.##", "Brgy.Jaro.#", "brgy jaro", None, 5]:
            self.assertFalse(tm.is_valid_pattern(p), repr(p))


class TopicValidationTest(unittest.TestCase):

    def test_incident(self):
        self.assertEqual(tm.parse_topic("brgy.jaro.purok-1.fire"),
                         {"kind": "incident", "barangay": "jaro",
                          "purok": "purok-1", "category": "fire"})
        self.assertTrue(tm.is_incident_topic("brgy.molo.purok-3.noise"))

    def test_incident_rejects_unknown_category_and_wildcards(self):
        self.assertFalse(tm.is_valid_topic("brgy.jaro.purok-1.earthquake"))
        self.assertFalse(tm.is_valid_topic("brgy.jaro.*.fire"))
        self.assertFalse(tm.is_valid_topic("brgy.jaro.#"))
        self.assertFalse(tm.is_valid_topic("brgy.jaro.purok-1.fire.extra"))

    def test_other_kinds(self):
        self.assertEqual(tm.parse_topic("brgy.jaro.advisory"),
                         {"kind": "advisory", "barangay": "jaro"})
        self.assertEqual(tm.parse_topic("report.ab12cd34.status"),
                         {"kind": "status", "report_id": "ab12cd34"})
        self.assertEqual(tm.parse_topic("city.iloilo.escalated.jaro"),
                         {"kind": "escalation", "barangay": "jaro"})
        # Only incident topics can be REPORTed to.
        self.assertFalse(tm.is_incident_topic("brgy.jaro.advisory"))
        self.assertFalse(tm.is_incident_topic("report.ab12cd34.status"))

    def test_unknown_shapes(self):
        for t in ["", "foo.bar", "city.cebu.escalated.jaro", "report.x.y",
                  "brgy.jaro", "brgy.jaro.purok-1.Fire", None]:
            self.assertFalse(tm.is_valid_topic(t), repr(t))


class BuildersTest(unittest.TestCase):

    def test_builders_round_trip(self):
        self.assertEqual(tm.incident_topic("jaro", "purok-1", "fire"), "brgy.jaro.purok-1.fire")
        self.assertEqual(tm.advisory_topic("jaro"), "brgy.jaro.advisory")
        self.assertEqual(tm.status_topic("ab12cd34"), "report.ab12cd34.status")
        self.assertEqual(tm.escalation_topic("jaro"), "city.iloilo.escalated.jaro")
        for t in [tm.incident_topic("jaro", "purok-1", "fire"), tm.advisory_topic("jaro"),
                  tm.status_topic("ab12cd34"), tm.escalation_topic("jaro")]:
            self.assertTrue(tm.is_valid_topic(t), t)

    def test_priority(self):
        for c in ("fire", "fight", "flood"):
            self.assertEqual(tm.priority_for(c), "URGENT")
        for c in ("noise", "drinking", "suspicious", "animals", "road"):
            self.assertEqual(tm.priority_for(c), "NORMAL")

    def test_normalize(self):
        self.assertEqual(tm.normalize_level("  Purok 3 "), "purok-3")
        self.assertEqual(tm.normalize_level("Sto. Niño"), "sto-nio")
        self.assertEqual(tm.normalize("BRGY.Jaro.#"), "brgy.jaro.#")


if __name__ == "__main__":
    unittest.main()
