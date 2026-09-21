from unittest import mock

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

EXPECTED_TOOLS = {
    "storage_list_backends",
    "storage_list_files",
    "storage_stat_file",
    "storage_read_file",
    "storage_get_upload_url",
    "storage_get_download_url",
    "storage_stage_upload",
    "storage_commit_upload",
    "storage_delete_file",
}


@tagged("post_install", "-at_install")
class TestStorageMcpTools(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env.ref("storage_backend.default_storage_backend")
        cls.Tool = cls.env["storage.mcp.tool"]

    def test_all_storage_tools_registered(self):
        self.env["llm.tool"]._scan_tool_decorators()
        names = {
            values["name"]
            for (model, method), values in self.env["llm.tool"]._tool_registry.items()
            if values["name"].startswith("storage_")
        }
        self.assertTrue(EXPECTED_TOOLS.issubset(names))

    def test_governance_flags_default_off(self):
        self.assertFalse(self.backend.mcp_read_enabled)
        self.assertFalse(self.backend.mcp_write_enabled)

    def test_write_tool_rejected_when_disabled(self):
        self.backend.mcp_write_enabled = False
        with self.assertRaises(UserError):
            self.Tool.storage_get_upload_url(self.backend.name, "x.txt")

    def test_upload_url_requires_overwrite_flag(self):
        self.backend.mcp_write_enabled = True
        with self.backend.open("x.txt", "wb") as f:
            f.write(b"x")
        with self.assertRaises(UserError):
            self.Tool.storage_get_upload_url(self.backend.name, "x.txt")
        result = self.Tool.storage_get_upload_url(self.backend.name, "x.txt", overwrite=True)
        self.assertIn("upload", result)

    def test_fallback_to_relay_when_no_presign(self):
        self.backend.mcp_write_enabled = True
        result = self.Tool.storage_get_upload_url(self.backend.name, "x.txt")
        self.assertIn("/storage_mcp/t/", result["upload"]["url"])

    def test_presigned_url_passthrough(self):
        self.backend.mcp_write_enabled = True
        presigned = {"url": "https://s3/x", "method": "PUT", "headers": {"X": "y"}}
        with mock.patch.object(type(self.backend), "presign_upload", return_value=presigned):
            result = self.Tool.storage_get_upload_url(self.backend.name, "x.txt")
        self.assertEqual(result["upload"]["url"], "https://s3/x")
        self.assertEqual(result["upload"]["method"], "PUT")

    def test_access_error_for_unauthorized_user(self):
        self.backend.mcp_read_enabled = True
        user = self.env["res.users"].create({
            "name": "No Access", "login": "noaccess@example.com",
        })
        with self.assertRaises(AccessError):
            self.env["storage.mcp.tool"].with_user(user).storage_list_files(self.backend.name)
