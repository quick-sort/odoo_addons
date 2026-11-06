import ast
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged

ADDON_ROOT = Path(__file__).resolve().parents[1]
FIELD_DIR = ADDON_ROOT / "static" / "src" / "fields" / "color_picker"


@tagged("post_install", "-at_install")
class TestColorPickerWidgetContract(TransactionCase):
    def _manifest(self):
        return ast.literal_eval((ADDON_ROOT / "__manifest__.py").read_text())

    def test_manifest_has_no_description(self):
        self.assertNotIn("description", self._manifest())

    def test_assets_declared(self):
        backend = self._manifest()["assets"]["web.assets_backend"]
        for suffix in (".js", ".xml"):
            self.assertTrue(
                any(path.endswith(suffix) for path in backend),
                f"web.assets_backend missing a {suffix} entry",
            )

    def test_widget_registered(self):
        js = (FIELD_DIR / "color_picker_field.js").read_text()
        self.assertIn(
            'registry.category("fields").add("compact_color_picker"', js
        )
        self.assertIn('supportedTypes: ["integer"]', js)
        self.assertIn("{ save: true }", js)

    def test_template_present(self):
        xml = (FIELD_DIR / "color_picker_field.xml").read_text()
        self.assertIn(
            't-name="web_widget_color_picker.CompactColorPickerField"', xml
        )
        self.assertIn("<ColorList", xml)

    def test_readme_present(self):
        self.assertTrue((ADDON_ROOT / "README.rst").is_file())
