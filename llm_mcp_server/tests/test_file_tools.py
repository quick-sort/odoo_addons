import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.misc import verify_limited_field_access_token

from ..file_service import DOWNLOAD_SCOPE, UPLOAD_SCOPE

TOOL_NAMES = {
    "attachment_stage_upload",
    "attachment_commit_upload",
    "attachment_get_download_url",
}


@tagged("post_install", "-at_install")
class TestFileTools(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tool = cls.env["llm.mcp.file.tool"]
        cls.Upload = cls.env["llm.mcp.file.upload"]

    def _user(self, login):
        return self.env["res.users"].create({
            "name": login,
            "login": login,
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })

    def _stage(self, user, name="file.bin"):
        result = self.Tool.with_user(user).attachment_stage_upload(name)
        attachment = self.env["ir.attachment"].browse(result["attachment_id"])
        upload = self.Upload.search([("attachment_id", "=", attachment.id)])
        return result, attachment, upload

    def _stage_uploaded(self, user, name="file.bin", data=b"hello"):
        result, attachment, upload = self._stage(user, name)
        attachment.sudo().write({"raw": data})
        upload.sudo().write({"state": "uploaded"})
        return result, attachment, upload

    def test_tools_registered_for_internal_users(self):
        self.env["llm.tool"]._scan_tool_decorators()
        registry = {
            values["name"]: values
            for values in self.env["llm.tool"]._tool_registry.values()
            if values["name"] in TOOL_NAMES
        }
        self.assertEqual(set(registry), TOOL_NAMES)
        for name, values in registry.items():
            self.assertEqual(values["code_group_xmlids"], '["base.group_user"]', name)

        # Use active_test=False: an upgrade run with --test-enable can leave code
        # tools inactive in the test database even though the declaration and
        # group sync are correct.
        tools = self.env["llm.tool"].with_context(active_test=False).search([
            ("name", "in", list(TOOL_NAMES)),
        ])
        self.assertEqual(set(tools.mapped("name")), TOOL_NAMES)
        for tool in tools:
            self.assertEqual(tool.code_group_xmlids, '["base.group_user"]', tool.name)
            self.assertIn(
                self.env.ref("base.group_user"), tool.allowed_group_ids, tool.name
            )

    def test_stage_creates_private_unbound_attachment(self):
        user = self._user("file_stage_owner")
        result, attachment, upload = self._stage(user, "hello.txt")
        self.assertFalse(attachment.res_model)
        self.assertFalse(attachment.res_id)
        self.assertFalse(attachment.public)
        self.assertFalse(attachment.raw)
        self.assertEqual(attachment.create_uid, user)
        self.assertEqual(upload.state, "pending")
        self.assertIn("/mcp/files/", result["upload"]["url"])
        self.assertIn("access_token=", result["upload"]["url"])

        other = self._user("file_stage_other")
        with self.assertRaises(AccessError):
            self.env["ir.attachment"].with_user(other).browse(attachment.id).check_access(
                "read"
            )

    def test_upload_token_is_scope_isolated(self):
        user = self._user("file_scope_owner")
        result, attachment, _upload = self._stage(user)
        token = parse_qs(urlparse(result["upload"]["url"]).query)["access_token"][0]
        self.assertTrue(
            verify_limited_field_access_token(attachment, "raw", token, scope=UPLOAD_SCOPE)
        )
        self.assertFalse(
            verify_limited_field_access_token(
                attachment, "raw", token, scope=DOWNLOAD_SCOPE
            )
        )

    def test_commit_requires_uploaded_bytes(self):
        user = self._user("file_commit_owner")
        _result, attachment, _upload = self._stage(user)
        with self.assertRaises(UserError):
            self.Tool.with_user(user).attachment_commit_upload(attachment.id)

    def test_commit_returns_sha256_and_size(self):
        user = self._user("file_commit_ok")
        data = b"hello file"
        result, attachment, _upload = self._stage_uploaded(user, data=data)
        out = self.Tool.with_user(user).attachment_commit_upload(attachment.id)
        self.assertEqual(out["attachment_id"], attachment.id)
        self.assertEqual(out["state"], "committed")
        self.assertEqual(out["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(out["size"], len(data))

    def test_commit_binding_enforces_target_write_access(self):
        user = self._user("file_bind_owner")
        partner = self.env["res.partner"].create({"name": "Customer"})
        _result, attachment, _upload = self._stage_uploaded(user)
        # res.partner is read-only for base.group_user, so binding as a regular
        # user must be rejected by the core write check.
        with self.assertRaises(AccessError):
            self.Tool.with_user(user).attachment_commit_upload(
                attachment.id, "res.partner", partner.id
            )

        _result, admin_attachment, _upload = self._stage_uploaded(self.env.user)
        out = self.Tool.attachment_commit_upload(
            admin_attachment.id, "res.partner", partner.id
        )
        self.assertEqual(admin_attachment.res_model, "res.partner")
        self.assertEqual(admin_attachment.res_id, partner.id)
        self.assertEqual(out["res_model"], "res.partner")

    def test_download_url_respects_attachment_access(self):
        user = self._user("file_download_owner")
        _result, attachment, _upload = self._stage_uploaded(user)
        self.Tool.with_user(user).attachment_commit_upload(attachment.id)

        out = self.Tool.with_user(user).attachment_get_download_url(attachment.id)
        self.assertIn("/web/content/ir.attachment/", out["download"]["url"])
        self.assertIn("access_token=", out["download"]["url"])

        other = self._user("file_download_other")
        with self.assertRaises(AccessError):
            self.Tool.with_user(other).attachment_get_download_url(attachment.id)

        # An attachment bound by an admin to a readable record becomes readable
        # by other internal users.
        partner = self.env["res.partner"].create({"name": "Shared"})
        _result, bound, _upload = self._stage_uploaded(self.env.user, name="shared.bin")
        self.Tool.attachment_commit_upload(bound.id, "res.partner", partner.id)
        self.Tool.with_user(other).attachment_get_download_url(bound.id)

    def test_download_url_denies_bound_record_without_access(self):
        owner = self._user("file_bound_owner")
        other = self._user("file_bound_other")
        # llm.mcp.file.upload has an owner-only record rule, so binding to one
        # of the owner's staging rows exercises the bound-record ACL path.
        owner_upload = self.Upload.with_user(owner).create({
            "name": "owned.bin",
            "expires_at": fields.Datetime.now() + timedelta(hours=1),
        })
        _result, attachment, _upload = self._stage_uploaded(self.env.user)
        self.Tool.attachment_commit_upload(
            attachment.id, "llm.mcp.file.upload", owner_upload.id
        )

        self.Tool.with_user(owner).attachment_get_download_url(attachment.id)
        with self.assertRaises(AccessError):
            self.Tool.with_user(other).attachment_get_download_url(attachment.id)

    def test_guide_is_visible_to_internal_users(self):
        guide = self.env.ref("llm_mcp_server.guide_file")
        self.assertEqual(guide.allowed_group_ids, self.env.ref("base.group_user"))
        user = self._user("file_guide_user")
        self.assertIn(guide, self.env["llm.tool.guide"].with_user(user)._readable_guides())
