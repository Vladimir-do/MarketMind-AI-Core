"""Regression tests for app/editor/schemas.py:normalize_card_payload().

D30 (docs/STABILIZATION_AUDIT.md): unlike its sibling fields `tags` and
`selling_points` in the very same function, `image_urls` had no
isinstance(str) guard. A raw string (as can arrive unchecked through
POST/PATCH .../drafts and .../quality-preview -- see D30 investigation)
was exploded character-by-character via `for item in "some string"`
instead of being treated as a single URL or a comma-separated list.
"""

import unittest

from app.editor.schemas import normalize_card_payload


class NormalizeCardPayloadImageUrlsTests(unittest.TestCase):
    def test_list_of_urls_is_kept_as_is(self):
        urls = ["https://example.com/a.jpg", "https://example.com/b.jpg"]
        result = normalize_card_payload({"image_urls": urls})
        self.assertEqual(result["image_urls"], urls)

    def test_list_deduplicates_and_strips(self):
        result = normalize_card_payload(
            {"image_urls": [" https://example.com/a.jpg ", "https://example.com/a.jpg", ""]}
        )
        self.assertEqual(result["image_urls"], ["https://example.com/a.jpg"])

    def test_empty_list_stays_empty(self):
        result = normalize_card_payload({"image_urls": []})
        self.assertEqual(result["image_urls"], [])

    def test_empty_string_is_treated_as_no_images(self):
        result = normalize_card_payload({"image_urls": ""})
        self.assertEqual(result["image_urls"], [])

    def test_none_is_treated_as_no_images(self):
        result = normalize_card_payload({"image_urls": None})
        self.assertEqual(result["image_urls"], [])

    def test_single_url_string_is_treated_as_one_url_not_exploded_into_characters(self):
        url = "https://example.com/a.jpg"
        result = normalize_card_payload({"image_urls": url})
        self.assertEqual(
            result["image_urls"],
            [url],
            "a raw string must become a one-item list, not one 'URL' per character",
        )

    def test_comma_separated_url_string_is_split_into_real_urls(self):
        result = normalize_card_payload({"image_urls": "https://a.com/1.jpg,https://a.com/2.jpg"})
        self.assertEqual(
            result["image_urls"],
            ["https://a.com/1.jpg", "https://a.com/2.jpg"],
        )

    def test_comma_separated_url_string_strips_whitespace_around_items(self):
        result = normalize_card_payload({"image_urls": "https://a.com/1.jpg, https://a.com/2.jpg ,  "})
        self.assertEqual(
            result["image_urls"],
            ["https://a.com/1.jpg", "https://a.com/2.jpg"],
        )


if __name__ == "__main__":
    unittest.main()
