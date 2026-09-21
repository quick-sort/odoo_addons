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
        cls.backend = cls.env.ref("storage_backend.default_storage_backend")
        cls.Upload = cls.env["storage.upload"]
        cls.Tool = cls.env["llm.page.tool"]

    def _stage(self, filename, data):
        path = self.Upload._stage_path(filename)
        upload = self.Upload.create({
            "name": filename,
            "backend_id": self.backend.id,
            "relative_path": path,
        })
        with self.backend.open(path, "wb") as stream:
            stream.write(data)
        upload.commit()
        return upload

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
        upload = self._stage("page.html", data)
        result = self.Tool.llm_page_create(upload.id, "Hello", "hello-page")
        page = self.env["llm.page"].browse(result["page_id"])
        self.assertEqual(page.state, "draft")
        self.assertEqual(page.html, "<h1>Hello</h1>")
        self.assertEqual(page.slug, "hello-page")
        self.assertEqual(page.source_backend_id, self.backend)
        self.assertEqual(page.source_size_bytes, len(data))

    def test_create_submit_directly(self):
        upload = self._stage("page.html", b"<p>x</p>")
        result = self.Tool.llm_page_create(upload.id, "X", "x-page", submit=True)
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
        empty = self._stage("empty.html", b"")
        with self.assertRaises(UserError):
            self.Tool.llm_page_create(empty.id, "E", "empty-page")
        # Invalid upload is left staged, so it can be fixed and retried.
        self.assertEqual(empty.state, "staged")

        bad = self._stage("bad.html", b"\xff\xfe\x00")
        with self.assertRaises(UserError):
            self.Tool.llm_page_create(bad.id, "B", "bad-page")
        self.assertEqual(bad.state, "staged")

    def test_source_audit(self):
        data = b"<p>audit</p>"
        upload = self._stage("audit.html", data)
        result = self.Tool.llm_page_create(upload.id, "Audit", "audit-page")
        page = self.env["llm.page"].browse(result["page_id"])
        self.assertEqual(page.source_sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(upload.state, "consumed")
        self.assertEqual(upload.consumed_model, "llm.page")
        self.assertEqual(upload.consumed_res_id, page.id)
