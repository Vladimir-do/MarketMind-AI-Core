"""Tests for the import pipeline."""

import unittest
from pathlib import Path

from app.pipeline import ImportPipeline, PipelineResult
from app.products.schema import UnifiedProduct
from app.products.validator import ProductValidator


class ProductValidatorTests(unittest.TestCase):
    """Tests for ProductValidator."""

    def setUp(self):
        self.validator = ProductValidator()

    def test_validator_catches_empty_name(self):
        """Test that validator catches empty product name."""
        product = UnifiedProduct(name="", source_id="123", source_type="test")
        valid_products, errors = self.validator.validate([product])
        
        self.assertEqual(len(valid_products), 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "required_name")
        self.assertEqual(errors[0].severity, "error")

    def test_validator_catches_missing_source_id(self):
        """Test that validator catches missing source_id."""
        product = UnifiedProduct(name="Test Product", source_id="", source_type="test")
        valid_products, errors = self.validator.validate([product])
        
        self.assertEqual(len(valid_products), 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "required_source_id")
        self.assertEqual(errors[0].severity, "error")

    def test_validator_passes_valid_product(self):
        """Test that valid product passes validation."""
        product = UnifiedProduct(
            name="Valid Product",
            source_id="123",
            source_type="test",
            price=1000,
        )
        valid_products, errors = self.validator.validate([product])
        
        self.assertEqual(len(valid_products), 1)
        self.assertEqual(len(errors), 0)

    def test_validator_warns_price_range(self):
        """Test that validator warns about price exceeding range."""
        product = UnifiedProduct(
            name="Expensive Product",
            source_id="123",
            source_type="test",
            price=60_000_000,
        )
        valid_products, errors = self.validator.validate([product])
        
        self.assertEqual(len(valid_products), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].rule, "price_range")
        self.assertEqual(errors[0].severity, "warning")


class ImportPipelineTests(unittest.TestCase):
    """Tests for ImportPipeline."""

    def test_pipeline_import_csv(self):
        """Test pipeline imports from CSV file."""
        csv_content = "name,source_id,price\nProduct A,123,1000\nProduct B,456,2000\n"
        csv_path = Path("/tmp/test_import.csv")
        csv_path.write_text(csv_content, encoding="utf-8")
        
        try:
            pipeline = ImportPipeline()
            result = pipeline.run_file(csv_path)
            
            self.assertIsInstance(result, PipelineResult)
            self.assertEqual(len(result.enriched), 2)
            self.assertEqual(result.enriched[0].product.name, "Product A")
            self.assertEqual(result.enriched[0].product.price, 1000)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_pipeline_import_string(self):
        """Test pipeline imports from string content."""
        csv_content = "name,source_id,price\nProduct X,789,3000\n"
        
        pipeline = ImportPipeline()
        result = pipeline.run_string(csv_content, "test.csv")
        
        self.assertIsInstance(result, PipelineResult)
        self.assertEqual(len(result.enriched), 1)
        self.assertEqual(result.enriched[0].product.name, "Product X")

    def test_pipeline_enrichment_produces_draft(self):
        """Test that pipeline enrichment produces OzonCardDraft."""
        product = UnifiedProduct(
            name="Test Product",
            source_id="123",
            source_type="test",
            price=1000,
            description="Test description for the product",
            category="Electronics",
        )
        
        pipeline = ImportPipeline()
        result = pipeline.run_products([product])
        
        self.assertEqual(len(result.enriched), 1)
        enriched = result.enriched[0]
        self.assertIsNotNone(enriched.draft)
        self.assertEqual(enriched.product.name, "Test Product")
        self.assertGreater(enriched.quality_score, 0)

    def test_pipeline_full_csv_pipeline(self):
        """Test full CSV pipeline: import → validate → enrich."""
        csv_content = """name,source_id,price,old_price,description
Good Product,123,1000,1500,Good product description
Expensive Product,789,60000000,70000000,Very expensive product
"""
        csv_path = Path("/tmp/test_full_pipeline.csv")
        csv_path.write_text(csv_content, encoding="utf-8")
        
        try:
            pipeline = ImportPipeline()
            result = pipeline.run_file(csv_path)
            
            # Both products pass validation (price_range is only a warning)
            self.assertEqual(len(result.enriched), 2)
            
            # Should have price_range warning
            from app.products.validator import ValidationError as VE
            validation_errors = [e for e in result.errors if isinstance(e, VE)]
            error_rules = {e.rule for e in validation_errors}
            self.assertIn("price_range", error_rules)
            
            # Check that enrichment happened
            for enriched in result.enriched:
                self.assertIsNotNone(enriched.draft)
                self.assertGreater(enriched.quality_score, 0)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_pipeline_validation_through_run_products(self):
        """Test validation filters invalid products when run via run_products."""
        products = [
            UnifiedProduct(name="Valid", source_id="1", source_type="test", price=100),
            UnifiedProduct(name="", source_id="2", source_type="test", price=200),
            UnifiedProduct(name="No ID", source_id="", source_type="test", price=300),
            UnifiedProduct(name="High Price", source_id="3", source_type="test", price=60_000_000),
        ]
        
        pipeline = ImportPipeline()
        result = pipeline.run_products(products)
        
        # Only "Valid" and "High Price" pass (missing source_id is error, empty name is error)
        self.assertEqual(len(result.enriched), 2)
        self.assertEqual(result.enriched[0].product.name, "Valid")
        self.assertEqual(result.enriched[1].product.name, "High Price")
        
        from app.products.validator import ValidationError as VE
        validation_errors = [e for e in result.errors if isinstance(e, VE)]
        error_rules = {e.rule for e in validation_errors}
        self.assertIn("required_name", error_rules)
        self.assertIn("required_source_id", error_rules)
        self.assertIn("price_range", error_rules)


if __name__ == "__main__":
    unittest.main()