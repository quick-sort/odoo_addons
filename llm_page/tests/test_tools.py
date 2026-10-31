import hashlib

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

EXPECTED_TOOLS = {
    "llm_page_create",
    "llm_page_list",
    "llm_page_status",
    "llm_page_submit",
}


@tagged("post_install", "-at_install")
class TestLlmPageTools(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tool = cls.env["llm.page.tool"]

    def _attachment(self, filename, data):
        attachment = self.env["ir.attachment"].create({"name": filename})
        attachment.write({"raw": data})
        return attachment

    def test_all_tools_registered(self):
        self.env["llm.tool"]._scan_tool_decorators()
        names = {
            values["name"]
            for (_model, _method), values in self.env["llm.tool"]._tool_registry.items()
            if values["name"].startswith("llm_page_")
        }
        self.assertTrue(EXPECTED_TOOLS.issubset(names))

    def test_create_from_upload(self):
        data = b"<h1>Hello</h1>"
        attachment = self._attachment("page.html", data)
        result = self.Tool.llm_page_create(attachment.id, "Hello", "hello-page")
        page = self.env["llm.page"].browse(result["page_id"])
        self.assertEqual(page.state, "draft")
        self.assertEqual(page.html, "<h1>Hello</h1>")
        self.assertEqual(page.slug, "hello-page")
        self.assertEqual(page.source_attachment_id, attachment)
        self.assertEqual(page.source_size_bytes, len(data))
        self.assertEqual(attachment.res_model, "llm.page")
        self.assertEqual(attachment.res_id, page.id)

    def test_create_submit_directly(self):
        attachment = self._attachment("page.html", b"<p>x</p>")
        result = self.Tool.llm_page_create(
            attachment.id, "X", "x-page", submit=True
        )
        self.assertEqual(result["state"], "pending")

    def test_body_extraction_full_document(self):
        full = (
            "<html><head><title>t</title></head>"
            "<body><h1>Hi</h1><script>alert(1)</script></body></html>"
        )
        self.assertEqual(
            self.Tool._extract_body(full),
            "<h1>Hi</h1><script>alert(1)</script>",
        )

    def test_body_extraction_fragment(self):
        self.assertEqual(
            self.Tool._extract_body("<div>Hello</div>"),
            "<div>Hello</div>",
        )

    def test_invalid_content_rejected(self):
        empty = self._attachment("empty.html", b"")
        with self.assertRaises(UserError):
            self.Tool.llm_page_create(empty.id, "E", "empty-page")
        # The attachment is untouched, so it can be fixed and retried.
        self.assertTrue(empty.exists())
        self.assertFalse(empty.res_model)

        bad = self._attachment("bad.html", b"\xff\xfe\x00")
        with self.assertRaises(UserError):
            self.Tool.llm_page_create(bad.id, "B", "bad-page")
        self.assertTrue(bad.exists())
        self.assertFalse(bad.res_model)

    def test_rejects_already_used_attachment(self):
        attachment = self._attachment("page.html", b"<p>first</p>")
        self.Tool.llm_page_create(attachment.id, "First", "first-page")
        with self.assertRaises(UserError):
            self.Tool.llm_page_create(attachment.id, "Second", "second-page")

    def test_source_audit(self):
        data = b"<p>audit</p>"
        attachment = self._attachment("audit.html", data)
        result = self.Tool.llm_page_create(attachment.id, "Audit", "audit-page")
        page = self.env["llm.page"].browse(result["page_id"])
        self.assertEqual(page.source_sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(page.source_size_bytes, len(data))
        self.assertEqual(page.source_attachment_id, attachment)
        self.assertEqual(attachment.res_model, "llm.page")
        self.assertEqual(attachment.res_id, page.id)
