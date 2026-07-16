"""Tests for the Universal Import Layer (P1.3)."""

from __future__ import annotations

from pathlib import Path


from app.importers.csv_importer import CsvImporter
from app.importers.registry import import_file
from app.products.schema import UnifiedProduct


class TestUnifiedProduct:
    def test_to_dict(self) -> None:
        p = UnifiedProduct(name="Тест", source_id="1", source_type="manual", price=1000)
        d = p.to_dict()
        assert d["name"] == "Тест"
        assert d["price"] == 1000
        assert d["source_type"] == "manual"

    def test_to_card_task_basic(self) -> None:
        p = UnifiedProduct(
            name="Кроссовки Nike",
            source_id="nk-001",
            source_type="file_import",
            brand="Nike",
            price=5990,
        )
        text = p.to_card_task()
        assert "название: Кроссовки Nike" in text
        assert "бренд: Nike" in text
        assert "цена: 5990 руб" in text

    def test_to_card_task_with_optional_fields(self) -> None:
        p = UnifiedProduct(
            name="Чайник",
            source_id="ch-1",
            source_type="file_import",
            price=1200,
            old_price=1500,
            discount_pct=20,
            weight_g=800,
            image_urls=["https://example.com/img.jpg"],
        )
        text = p.to_card_task()
        assert "старая цена: 1500 руб" in text
        assert "скидка: 20%" in text
        assert "вес: 800 г" in text
        assert "фото: https://example.com/img.jpg" in text


class TestCsvImporter:
    def test_can_handle(self) -> None:
        assert CsvImporter.can_handle("data.csv") is True
        assert CsvImporter.can_handle("data.xlsx") is False
        assert CsvImporter.can_handle("data.csv.bak") is False

    def test_validate_missing(self) -> None:
        errors = CsvImporter().validate("/nonexistent/file.csv")
        assert len(errors) == 1
        assert "not found" in errors[0].lower() or "not found" in errors[0]

    def test_import_csv_russian_headers(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "товары.csv"
        csv_file.write_text(
            "название,бренд,цена,старая цена,описание,категория\n"
            "Кроссовки RunMax,RunMax,4500,5200,Беговые кроссовки,Обувь\n"
            "Футболка Classic,TeeCo,1200,,Хлопковая футболка,Одежда\n",
            encoding="utf-8",
        )
        result = import_file(csv_file)
        assert len(result.errors) == 0
        assert len(result.products) == 2

        p1 = result.products[0]
        assert p1.name == "Кроссовки RunMax"
        assert p1.brand == "RunMax"
        assert p1.price == 4500
        assert p1.old_price == 5200
        assert p1.description == "Беговые кроссовки"
        assert p1.category == "Обувь"

        p2 = result.products[1]
        assert p2.name == "Футболка Classic"
        assert p2.price == 1200
        assert p2.old_price is None

    def test_import_csv_english_headers(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "products.csv"
        csv_file.write_text(
            "name,brand,price,description\n"
            "Widget X,WX Corp,999,A useful widget\n",
            encoding="utf-8",
        )
        result = import_file(csv_file)
        assert len(result.errors) == 0
        assert len(result.products) == 1
        assert result.products[0].name == "Widget X"
        assert result.products[0].brand == "WX Corp"
        assert result.products[0].price == 999

    def test_to_card_task_after_import(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "items.csv"
        csv_file.write_text(
            "название,бренд,цена\n"
            "Набор ножей,SteelPro,3500\n",
            encoding="utf-8",
        )
        result = import_file(csv_file)
        assert len(result.products) == 1
        text = result.products[0].to_card_task()
        assert "название: Набор ножей" in text
        assert "бренд: SteelPro" in text
        assert "цена: 3500 руб" in text

    def test_empty_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("название,бренд,цена\n", encoding="utf-8")
        result = import_file(csv_file)
        assert len(result.products) == 0
        assert len(result.errors) == 0

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        txt_file = tmp_path / "data.txt"
        txt_file.write_text("hello", encoding="utf-8")
        result = import_file(txt_file)
        assert len(result.errors) == 1


class TestRegistry:
    def test_import_file_routes_to_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("название,цена\nТовар,100\n", encoding="utf-8")
        result = import_file(csv_file)
        assert len(result.products) == 1
        assert result.metadata["source"] == str(csv_file)


SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"


class TestDemoFiles:
    """Validate that demo sample files exist and are importable."""

    def test_demo_csv_exists_and_imports(self) -> None:
        csv_path = SAMPLES_DIR / "products_demo.csv"
        assert csv_path.exists(), f"Demo CSV not found: {csv_path}"
        result = import_file(csv_path)
        assert len(result.products) >= 20, f"Expected >=20 products, got {len(result.products)}"
        assert len(result.errors) == 0, f"Import errors: {result.errors}"
        for p in result.products:
            assert p.name, "All products must have a name"
            assert p.price is not None, f"Product '{p.name}' must have a price"

    def test_demo_xlsx_exists_and_imports(self) -> None:
        xlsx_path = SAMPLES_DIR / "products_demo.xlsx"
        assert xlsx_path.exists(), f"Demo XLSX not found: {xlsx_path}"
        from app.importers.excel_importer import ExcelImporter

        imp = ExcelImporter()
        result = imp.import_data(xlsx_path)
        assert len(result.products) >= 20, f"Expected >=20 products, got {len(result.products)}"
        assert len(result.errors) == 0, f"Import errors: {result.errors}"

    def test_demo_csv_and_xlsx_match(self) -> None:
        csv_result = import_file(SAMPLES_DIR / "products_demo.csv")
        from app.importers.excel_importer import ExcelImporter

        xlsx_result = ExcelImporter().import_data(SAMPLES_DIR / "products_demo.xlsx")
        csv_names = sorted(p.name for p in csv_result.products)
        xlsx_names = sorted(p.name for p in xlsx_result.products)
        assert csv_names == xlsx_names, "CSV and XLSX demo files must contain the same products"


class TestWebImportRoutes:
    """Test the web-facing import endpoints (templates + demo)."""

    def test_download_csv_template(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.web.routes.import_ import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/import/template/csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        lines = resp.text.strip().split("\n")
        assert len(lines) >= 1, "Template must have at least a header row"
        header = lines[0]
        assert "название" in header
        assert "цена" in header

    def test_download_xlsx_template(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.web.routes.import_ import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/import/template/xlsx")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]

    def test_import_page_renders(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.web.routes.import_ import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/import")
        assert resp.status_code == 200
        assert "Импорт товаров" in resp.text
        assert "/api/import/template/csv" in resp.text
        assert "/api/import/template/xlsx" in resp.text
        assert "/api/import/demo" in resp.text
