import tempfile
import unittest
from pathlib import Path

from app.skill_manifest import (
    ScoringPolicy,
    SkillGraph,
    SkillManifest,
    SkillQuality,
    load_default_skill_graph,
    load_skill_manifests,
)


class SkillManifestTests(unittest.TestCase):
    def test_loads_yaml_manifests(self):
        graph = load_default_skill_graph()

        manifest = graph.get("scraping.website")

        self.assertEqual(manifest.category, "scraping")
        self.assertIn("html.fetch", manifest.requires)
        self.assertIn("scraping.manual_plan", manifest.fallback_to)

    def test_runtime_planner_manifests_include_available_executor_steps(self):
        graph = load_default_skill_graph()

        self.assertTrue(graph.get("scraping.fetch_pages").available)
        self.assertTrue(graph.get("scraping.extract_products").available)
        self.assertTrue(graph.get("scraping.validate_result").available)
        self.assertTrue(graph.get("csv.export").available)
        self.assertTrue(graph.get("page.classification.training").available)
        self.assertEqual(graph.get("scraping.generic").status, "missing")

    def test_graph_resolves_dependencies_before_skill(self):
        graph = SkillGraph([
            SkillManifest("html.fetch", "HTML Fetch", "scraping", status="available"),
            SkillManifest("html.parse", "HTML Parse", "scraping", status="available", requires=("html.fetch",)),
        ])

        resolution = graph.resolve(["html.parse"])

        self.assertTrue(resolution.executable)
        self.assertEqual([step.manifest.skill_id for step in resolution.steps], ["html.fetch", "html.parse"])

    def test_graph_selects_best_available_fallback(self):
        graph = SkillGraph([
            SkillManifest("primary", "Primary", "test", status="missing", fallback_to=("slow", "stable")),
            SkillManifest(
                "slow",
                "Slow",
                "test",
                status="available",
                quality=SkillQuality(reliability=0.5, speed=0.9, reuse=0.5, complexity=0.2),
            ),
            SkillManifest(
                "stable",
                "Stable",
                "test",
                status="available",
                quality=SkillQuality(reliability=0.95, speed=0.5, reuse=0.8, complexity=0.3),
            ),
        ])

        resolution = graph.resolve(["primary"])

        self.assertTrue(resolution.executable)
        self.assertEqual(resolution.steps[0].manifest.skill_id, "stable")
        self.assertEqual(resolution.steps[0].selected_for, "primary")

    def test_scoring_policy_changes_fallback_choice(self):
        graph = SkillGraph([
            SkillManifest("primary", "Primary", "test", status="missing", fallback_to=("fast", "stable")),
            SkillManifest(
                "fast",
                "Fast",
                "test",
                status="available",
                quality=SkillQuality(reliability=0.55, speed=0.98, reuse=0.5, complexity=0.2, risk=0.45),
            ),
            SkillManifest(
                "stable",
                "Stable",
                "test",
                status="available",
                quality=SkillQuality(reliability=0.95, speed=0.45, reuse=0.8, complexity=0.3, risk=0.08),
            ),
        ], scoring_policy=ScoringPolicy.FAST)

        self.assertEqual(graph.resolve(["primary"]).steps[0].manifest.skill_id, "fast")

        stable_graph = SkillGraph(list(graph.manifests), scoring_policy=ScoringPolicy.PRODUCTION_SAFE)

        self.assertEqual(stable_graph.resolve(["primary"]).steps[0].manifest.skill_id, "stable")

    def test_mermaid_graph_export_includes_dependencies_and_fallbacks(self):
        graph = load_default_skill_graph()

        mermaid = graph.to_mermaid(["scraping.website"])

        self.assertIn("graph TD", mermaid)
        self.assertIn("scraping.website", mermaid)
        self.assertIn("html.fetch", mermaid)
        self.assertIn("fallback", mermaid)

    def test_manifest_loader_reads_failure_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "skill.yaml"
            path.write_text(
                """
skill_id: market.search
name: Market Search
category: marketplace
status: available
failure_patterns:
  - site: ozon
    trigger: abt-challenge
    recovery: cooldown
    cooldown_seconds: 1200
""",
                encoding="utf-8",
            )

            manifests = load_skill_manifests(tmp)

        self.assertEqual(manifests[0].failure_patterns[0].trigger, "abt-challenge")
        self.assertEqual(manifests[0].failure_patterns[0].cooldown_seconds, 1200)


if __name__ == "__main__":
    unittest.main()
