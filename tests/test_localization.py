"""Tests for UI localization — verify no English strings in user-facing templates."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"

# Patterns that are ALLOWED in templates (code, not user-facing)
ALLOWED_PATTERNS = [
    r"^\s*#",  # Comments
    r"^\s*\{#",  # Jinja comments
    r"href=",  # HTML attributes
    r"class=",  # CSS classes
    r"hx-",  # HTMX attributes
    r"src=",  # Script sources
    r"style=",  # Inline styles
    r"{{.*}}",  # Jinja expressions
    r"{%.*%}",  # Jinja blocks
    r"Chart\(",  # Chart.js constructor
    r"getContext\(",  # Canvas API
    r"borderColor:",  # CSS in script
    r"backgroundColor:",  # CSS in script
    r"beginAtZero:",  # Chart.js config
    r"maxTicksLimit:",  # Chart.js config
    r"document\.",  # DOM API
    r"getElementById\(",  # DOM API
    r"classList\.",  # DOM API
    r"addEventListener\(",  # DOM API
    r"cdn\.",  # CDN URLs
    r"unpkg\.",  # CDN URLs
    r"jsdelivr\.",  # CDN URLs
    r"tailwindcss",  # Tailwind
    r"htmx",  # HTMX
]

# English words that should NOT appear in user-facing text
ENGLISH_WORDS = [
    "MarketMind",  # Brand name — allowed
    "AI",  # Abbreviation — allowed in "Предложения AI"
    "Dashboard",
    "Products",
    "Import",
    "Settings",
    "Reports",
    "Score",
    "Analytics",
    "Store",
    "Quality",
    "Approval",
    "History",
    "Price",
    "Product",
    "Suggestion",
    "Approve",
    "Reject",
    "Rollback",
    "Pending",
    "Approved",
    "Rejected",
    "No products",
    "No suggestions",
    "Search",
    "Filter",
    "Total",
    "Average",
    "Distribution",
    "Issues",
    "Attention",
    "Comparison",
    "Save",
    "Cancel",
    "Delete",
    "Edit",
    "Back",
    "Loading",
    "Error",
    "Success",
    "Confirm",
    "Yes",
    "No",
]


class LocalizationTests(unittest.TestCase):
    """Verify that user-facing templates contain no unexpected English text."""

    def test_no_english_in_templates(self):
        """Check that templates don't contain English UI text."""
        violations = []
        for template_file in TEMPLATES_DIR.glob("*.html"):
            content = template_file.read_text(encoding="utf-8")
            for line_num, line in enumerate(content.splitlines(), 1):
                # Skip code lines
                if any(re.search(p, line) for p in ALLOWED_PATTERNS):
                    continue
                # Skip empty lines and comment-only lines
                stripped = line.strip()
                if not stripped or stripped.startswith("{#"):
                    continue
                # Check for English words (case-sensitive, whole word)
                for word in ENGLISH_WORDS:
                    if re.search(rf"\b{re.escape(word)}\b", line):
                        violations.append(f"{template_file.name}:{line_num}: {word} in: {stripped[:80]}")

        if violations:
            self.fail("English text found in templates:\n" + "\n".join(violations[:20]))

    def test_locale_file_exists(self):
        """Verify Russian locale file exists and has keys."""
        locale_file = TEMPLATES_DIR.parent / "locales" / "ru.json"
        self.assertTrue(locale_file.exists(), f"Locale file not found: {locale_file}")
        import json
        with open(locale_file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertGreater(len(data), 50, "Locale file should have 50+ keys")
        # Check key categories exist
        for category in ["nav_", "dashboard_", "products_", "quality_", "findings_", "suggestions_", "import_", "analytics_"]:
            matching = [k for k in data if k.startswith(category)]
            self.assertGreater(len(matching), 0, f"Missing keys for category: {category}")

    def test_locale_load_function(self):
        """Verify locale loading works."""
        from app.web.locales import load_locale, t
        locale = load_locale("ru")
        self.assertIn("app_name", locale)
        self.assertEqual(t("app_name"), "MarketMind AI")
        self.assertEqual(t("nav_dashboard"), "Панель управления")
        self.assertEqual(t("nonexistent_key"), "nonexistent_key")  # falls back to key


if __name__ == "__main__":
    unittest.main()
