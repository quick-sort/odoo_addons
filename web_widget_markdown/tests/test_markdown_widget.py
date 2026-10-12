import ast
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged

ADDON_ROOT = Path(__file__).resolve().parents[1]


@tagged("post_install", "-at_install")
class TestMarkdownWidgetContract(TransactionCase):
    def _manifest(self):
        return ast.literal_eval((ADDON_ROOT / "__manifest__.py").read_text())

    def test_manifest_has_no_description(self):
        self.assertNotIn("description", self._manifest())

    def test_assets_declared(self):
        assets = self._manifest()["assets"]
        lib = assets["web_widget_markdown.assets_lib"]
        self.assertTrue(any("marked.min.js" in path for path in lib))
        backend = assets["web.assets_backend"]
        for suffix in (".js", ".xml", ".scss"):
            self.assertTrue(
                any(path.endswith(suffix) for path in backend),
                f"web.assets_backend missing a {suffix} entry",
            )

    def test_vendored_marked_lib_present(self):
        lib = ADDON_ROOT / "static" / "lib" / "marked" / "marked.min.js"
        self.assertTrue(lib.is_file(), "marked.min.js is missing")
        self.assertGreater(lib.stat().st_size, 10_000, "marked.min.js looks empty/truncated")

    def test_widget_registered(self):
        js = (
            ADDON_ROOT
            / "static"
            / "src"
            / "fields"
            / "markdown"
            / "markdown_field.js"
        ).read_text()
        self.assertIn('registry.category("fields").add("markdown"', js)

    def test_readme_present(self):
        self.assertTrue((ADDON_ROOT / "README.rst").is_file())
