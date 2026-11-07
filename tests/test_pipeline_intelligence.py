"""Tests for intelligence layer integration in the pipeline."""

import unittest
from pathlib import Path

from app.pipeline import ImportPipeline
from app.products.findings import AnalysisResult, BatchAnalysisResult
from app.products.schema import UnifiedProduct


class AnalysisPopulatedTests(unittest.TestCase):
    """Tests that analysis is populated on each product."""

    def test_analysis_populated_on_each_product(self):
        products = [
            UnifiedProduct(name="Product A", source_id="1", source_type="csv", price=100),
            UnifiedProduct(name="Product B", source_id="2", source_type="csv", price=200),
        ]
        pipeline = ImportPipeline()
        result = pipeline.run_products(products)

        self.assertEqual(len(result.enriched), 2)
        for ep in result.enriched:
            self.assertIsNotNone(ep.analysis)
            self.assertIsInstance(ep.analysis, AnalysisResult)
            self.assertIsInstance(ep.analysis.score, int)
            self.assertGreaterEqual(ep.analysis.score, 0)
            self.assertLessEqual(ep.analysis.score, 100)

    def test_analysis_populated_on_import_file(self):
        csv_content = "name,source_id,price\nProduct A,1,100\nProduct B,2,200\n"
        csv_path = Path("/tmp/test_intel_file.csv")
        csv_path.write_text(csv_content, encoding="utf-8")

        try:
            pipeline = ImportPipeline()
            result = pipeline.run_file(csv_path)

            for ep in result.enriched:
                self.assertIsNotNone(ep.analysis)
                self.assertIsInstance(ep.analysis, AnalysisResult)
        finally:
            csv_path.unlink(missing_ok=True)


class BatchAnalysisTests(unittest.TestCase):
    """Tests that batch analysis is populated on PipelineResult."""

    def test_batch_analysis_populated(self):
        products = [
            UnifiedProduct(name="Product A", source_id="1", source_type="csv", price=100),
            UnifiedProduct(name="Product B", source_id="2", source_type="csv", price=200),
        ]
        pipeline = ImportPipeline()
        result = pipeline.run_products(products)

        self.assertIsNotNone(result.batch_analysis)
        self.assertIsInstance(result.batch_analysis, BatchAnalysisResult)
        self.assertEqual(result.batch_analysis.total, 2)
        self.assertGreater(result.batch_analysis.average_score, 0)

    def test_batch_analysis_populated_on_import_file(self):
        csv_content = "name,source_id,price\nProduct A,1,100\nProduct B,2,200\n"
        csv_path = Path("/tmp/test_intel_batch.csv")
        csv_path.write_text(csv_content, encoding="utf-8")

        try:
            pipeline = ImportPipeline()
            result = pipeline.run_file(csv_path)

            self.assertIsNotNone(result.batch_analysis)
            self.assertIsInstance(result.batch_analysis, BatchAnalysisResult)
        finally:
            csv_path.unlink(missing_ok=True)


class AnalysisMetadataTests(unittest.TestCase):
    """Tests for analysis_metadata on PipelineResult."""

    def test_analysis_metadata_contains_expected_keys(self):
        products = [
            UnifiedProduct(name="Product A", source_id="1", source_type="csv", price=100),
        ]
        pipeline = ImportPipeline()
        result = pipeline.run_products(products)

        meta = result.analysis_metadata
        self.assertIn("analyzed", meta)
        self.assertIn("average_score", meta)
        self.assertIn("below_threshold", meta)
        self.assertIn("tier_distribution", meta)
        self.assertIn("top_issues", meta)

        self.assertEqual(meta["analyzed"], 1)
        self.assertIsInstance(meta["average_score"], float)
        self.assertIsInstance(meta["below_threshold"], int)
        self.assertIsInstance(meta["tier_distribution"], dict)
        self.assertIsInstance(meta["top_issues"], list)

    def test_top_issues_structure(self):
        product = UnifiedProduct(
            name="Product X",
            source_id="1",
            source_type="csv",
            price=100,
        )
        pipeline = ImportPipeline()
        result = pipeline.run_products([product])

        meta = result.analysis_metadata
        self.assertGreater(len(meta["top_issues"]), 0)
        issue = meta["top_issues"][0]
        self.assertIn("rule", issue)
        self.assertIn("action", issue)
        self.assertIn("priority", issue)


class FindingsTests(unittest.TestCase):
    """Tests that intelligence finds missing fields."""

    def test_intelligence_finds_missing_fields(self):
        product = UnifiedProduct(
            name="Product X",
            source_id="1",
            source_type="csv",
            price=100,
        )
        pipeline = ImportPipeline()
        result = pipeline.run_products([product])

        ep = result.enriched[0]
        self.assertIsNotNone(ep.analysis)
        self.assertGreater(len(ep.analysis.findings), 0)

        finding_rules = {f.rule for f in ep.analysis.findings}
        self.assertIn("completeness_brand", finding_rules)

    def test_intelligence_finds_missing_brand_and_category(self):
        product = UnifiedProduct(
            name="Product X",
            source_id="1",
            source_type="csv",
            price=100,
        )
        pipeline = ImportPipeline()
        result = pipeline.run_products([product])

        ep = result.enriched[0]
        finding_rules = {f.rule for f in ep.analysis.findings}
        self.assertIn("completeness_brand", finding_rules)
        self.assertIn("completeness_category", finding_rules)

    def test_quality_score_reflects_findings(self):
        product = UnifiedProduct(
            name="Minimal Product",
            source_id="1",
            source_type="csv",
            price=100,
        )
        pipeline = ImportPipeline()
        result = pipeline.run_products([product])

        ep = result.enriched[0]
        self.assertIsNotNone(ep.analysis)
        self.assertLess(ep.analysis.score, 75)
        self.assertIn(ep.analysis.tier, ("poor", "fair", "critical"))


class FullPipelineTests(unittest.TestCase):
    """Tests for full CSV → intelligence pipeline."""

    def test_full_csv_to_intelligence_pipeline(self):
        csv_content = """name,source_id,price,old_price,description,brand,category
Good Product,123,1000,1500,A detailed description of a great product,BrandX,Electronics
Bad Product,456,500,800,Short,BRAND,other
"""
        csv_path = Path("/tmp/test_full_intel.csv")
        csv_path.write_text(csv_content, encoding="utf-8")

        try:
            pipeline = ImportPipeline()
            result = pipeline.run_file(csv_path)

            # Both products pass validation
            self.assertEqual(len(result.enriched), 2)

            # Each product has analysis
            for ep in result.enriched:
                self.assertIsNotNone(ep.analysis)
                self.assertIsInstance(ep.analysis.score, int)
                self.assertGreaterEqual(ep.analysis.score, 0)
                self.assertLessEqual(ep.analysis.score, 100)
                self.assertGreater(len(ep.analysis.findings), 0)
                self.assertGreater(len(ep.analysis.recommendations), 0)

            # Batch analysis exists
            self.assertIsNotNone(result.batch_analysis)
            self.assertEqual(result.batch_analysis.total, 2)
            self.assertGreater(result.batch_analysis.average_score, 0)

            # Analysis metadata exists
            self.assertIn("analyzed", result.analysis_metadata)
            self.assertEqual(result.analysis_metadata["analyzed"], 2)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_empty_products_gives_empty_batch_analysis(self):
        pipeline = ImportPipeline()
        result = pipeline.run_products([])

        self.assertIsNotNone(result.batch_analysis)
        self.assertEqual(result.batch_analysis.total, 0)
        self.assertEqual(result.analysis_metadata["analyzed"], 0)


if __name__ == "__main__":
    unittest.main()
