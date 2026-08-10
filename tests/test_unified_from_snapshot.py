"""Regression tests for the suspected image_urls bug in
app/effective_card/service.py:_unified_from_snapshot().

Investigation summary (see docs/STABILIZATION_AUDIT.md D12 follow-up):
every real writer of the snapshot dict this function reads
(_snapshot_from_unified in app/projects/service.py, normalize_card_payload
in app/editor/schemas.py) already coerces image_urls to a list before it
is ever persisted. These tests characterize _unified_from_snapshot's own
behavior in isolation (it has no defensive handling of its own) and prove
list/None/empty are the only shapes it is ever actually called with.
"""

import unittest

from app.effective_card.service import _unified_from_snapshot


class UnifiedFromSnapshotDirectInputTests(unittest.TestCase):
    """Characterize _unified_from_snapshot's own (undefended) behavior for
    every input shape ETAP 1 identified as conceivable."""

    def test_single_url_list(self):
        product = _unified_from_snapshot({"image_urls": ["https://example.com/a.jpg"]}, 1)
        self.assertEqual(product.image_urls, ["https://example.com/a.jpg"])

    def test_multiple_url_list(self):
        urls = ["https://example.com/a.jpg", "https://example.com/b.jpg"]
        product = _unified_from_snapshot({"image_urls": urls}, 1)
        self.assertEqual(product.image_urls, urls)

    def test_none_is_treated_as_no_images(self):
        product = _unified_from_snapshot({"image_urls": None}, 1)
        self.assertEqual(product.image_urls, [])

    def test_missing_key_is_treated_as_no_images(self):
        product = _unified_from_snapshot({}, 1)
        self.assertEqual(product.image_urls, [])

    def test_empty_list(self):
        product = _unified_from_snapshot({"image_urls": []}, 1)
        self.assertEqual(product.image_urls, [])

    def test_empty_string_is_falsy_and_treated_as_no_images(self):
        # "" is falsy, so `snapshot.get("image_urls") or []` short-circuits
        # to [] before the (missing) string-handling would ever run.
        product = _unified_from_snapshot({"image_urls": ""}, 1)
        self.assertEqual(product.image_urls, [])

    def test_latent_defect_raw_string_is_split_into_individual_characters(self):
        """Documents (does not endorse) _unified_from_snapshot's actual,
        undefended behavior if it is ever called directly with a raw
        string -- confirmed unreachable via any current production path
        (see investigation notes), but real if this function is ever
        called with unsanitized data in the future."""
        url = "https://example.com/a.jpg"
        product = _unified_from_snapshot({"image_urls": url}, 1)
        self.assertNotEqual(
            product.image_urls, [url],
            "this assertion documents the bug: a raw string is NOT treated as "
            "a single URL, it is exploded into one-character 'URLs' instead",
        )
        # list("abc") == ["a", "b", "c"] -- every character becomes its own
        # "URL", no deduplication (unlike normalize_card_payload's version
        # of this same defect class).
        self.assertEqual(product.image_urls, list(url))
        self.assertEqual(len(product.image_urls), len(url))

    def test_latent_defect_comma_separated_string_also_splits_into_characters_not_urls(self):
        """Confirms _unified_from_snapshot does NOT do the comma-split
        handling its sibling app/ai_recommendation/job_queue.py:
        _build_project_unified() has -- a raw "url1,url2" string produces
        garbage, not two URLs."""
        product = _unified_from_snapshot({"image_urls": "https://a.com/1.jpg,https://a.com/2.jpg"}, 1)
        self.assertNotIn("https://a.com/1.jpg", product.image_urls)
        self.assertIn(",", product.image_urls, "comma ends up as a bogus one-character 'URL'")


if __name__ == "__main__":
    unittest.main()
