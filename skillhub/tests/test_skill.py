import hashlib

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from psycopg2 import errors


@tagged("post_install", "-at_install")
class TestSkillHub(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tool = cls.env["skillhub.tool"]
        cls.main_company = cls.env.ref("base.main_company")
        cls.owner_user = cls._make_user("skill_owner")
        # Administrators bypass the owner/shared/public record rules.
        cls.other_user = cls._make_user("skill_other", admin=True)
        cls.shared_user = cls._make_user("skill_shared")
        cls.plain_user = cls._make_user("skill_plain")

    @classmethod
    def _make_user(cls, login, admin=False):
        group_ids = [cls.env.ref("base.group_user").id]
        if admin:
            group_ids.append(cls.env.ref("base.group_system").id)
        return cls.env["res.users"].create({
            "name": login,
            "login": login,
            "company_id": cls.main_company.id,
            "company_ids": [Command.set([cls.main_company.id])],
            "group_ids": [Command.set(group_ids)],
        })

    def _make_attachment(self, user, data=b"zip-bytes", name="skill.zip"):
        attachment = self.env["ir.attachment"].with_user(user).create({
            "name": name,
        })
        attachment.write({"raw": data})
        return attachment

    def _publish(
        self,
        user,
        code,
        title,
        description="",
        version="",
        data=b"zip-bytes",
        category_id=0,
        depends_on_ids=None,
        attachment=None,
    ):
        attachment = attachment or self._make_attachment(user, data=data)
        result = self.Tool.with_user(user).skill_publish(
            attachment.id,
            code,
            title,
            description=description,
            version=version,
            category_id=category_id,
            depends_on_ids=depends_on_ids,
        )
        return self.env["skillhub.skill"].browse(result["skill_id"])

    # AC-1 -----------------------------------------------------------------

    def test_model_fields(self):
        field_names = set(self.env["skillhub.skill"]._fields)
        expected = {
            "code", "title", "description", "version", "is_public",
            "shared_user_ids", "category_id", "attachment_id",
            "size", "sha256", "depends_on_ids", "required_by_ids",
        }
        self.assertTrue(expected.issubset(field_names))
        self.assertNotIn("backend_id", field_names)
        self.assertNotIn("storage_path", field_names)

    def test_code_unique_and_slug(self):
        self._publish(self.owner_user, "dup", "Dup")
        with self.assertRaises(errors.UniqueViolation):
            self.env["skillhub.skill"].create({"code": "dup", "title": "X"})
        with self.assertRaises(UserError):
            self.Tool.with_user(self.owner_user).skill_publish(
                self._make_attachment(self.owner_user).id,
                "bad/code",
                "Bad Code",
            )

    def test_category_assigned(self):
        cat = self.env["skillhub.category"].create({"name": "Data"})
        skill = self._publish(self.owner_user, "cat", "Categorized", category_id=cat.id)
        self.assertEqual(skill.category_id, cat)

    def test_publish_keeps_category_when_omitted(self):
        cat = self.env["skillhub.category"].create({"name": "Data"})
        first = self._publish(self.owner_user, "keep", "V1", category_id=cat.id)
        second = self._publish(self.owner_user, "keep", "V2", data=b"v2")
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.category_id, cat)

    # AC-11 dependency -----------------------------------------------------

    def test_dependency_assigned_and_returned(self):
        dep = self._publish(self.owner_user, "dep", "Dependency")
        skill = self._publish(self.owner_user, "main", "Main")
        skill.write({"depends_on_ids": [Command.set([dep.id])]})
        self.assertEqual(skill.depends_on_ids, dep)
        self.assertEqual(dep.required_by_ids, skill)

    def test_publish_sets_dependencies(self):
        dep = self._publish(self.owner_user, "dep2", "Dependency 2")
        skill = self._publish(
            self.owner_user, "main2", "Main 2", depends_on_ids=[dep.id]
        )
        self.assertEqual(skill.depends_on_ids, dep)
        self.assertEqual(dep.required_by_ids, skill)

    def test_publish_keeps_dependencies_when_omitted(self):
        dep = self._publish(self.owner_user, "dep3", "Dependency 3")
        first = self._publish(
            self.owner_user, "keepdep", "V1", depends_on_ids=[dep.id]
        )
        second = self._publish(self.owner_user, "keepdep", "V2", data=b"v2")
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.depends_on_ids, dep)

    def test_self_dependency_rejected(self):
        skill = self._publish(self.owner_user, "selfdep", "Self")
        with self.assertRaises(ValidationError):
            skill.write({"depends_on_ids": [Command.set([skill.id])]})

    # AC-2 / AC-3 ----------------------------------------------------------

    def test_publish_creates_skill(self):
        data = b"hello-skill"
        skill = self._publish(self.owner_user, "demo", "Demo Skill", data=data)
        self.assertEqual(skill.code, "demo")
        self.assertEqual(skill.size, len(data))
        self.assertEqual(skill.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(skill.attachment_id.raw, data)
        self.assertEqual(skill.attachment_id.res_model, "skillhub.skill")
        self.assertEqual(skill.attachment_id.res_id, skill.id)

    def test_publish_updates_existing(self):
        first = self._publish(self.owner_user, "demo", "V1", version="1.0", data=b"v1")
        first_attachment = first.attachment_id
        second = self._publish(
            self.owner_user, "demo", "V2", version="2.0", data=b"v2-long"
        )
        self.assertEqual(first.id, second.id)
        skills = self.env["skillhub.skill"].search([("code", "=", "demo")])
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills.title, "V2")
        self.assertEqual(skills.size, len(b"v2-long"))
        self.assertEqual(skills.attachment_id.raw, b"v2-long")
        self.assertFalse(first_attachment.exists())

    def test_failed_publish_keeps_previous_package(self):
        """A failed publish leaves the skill pointing at its previous package."""
        first = self._publish(self.owner_user, "atomic", "V1", data=b"first-package")
        first_attachment = first.attachment_id
        second_attachment = self._make_attachment(
            self.owner_user, data=b"second-package"
        )
        with self.assertRaises(ValidationError):
            self.Tool.with_user(self.owner_user).skill_publish(
                second_attachment.id,
                "atomic",
                "V2",
                depends_on_ids=[first.id],
            )
        self.assertEqual(first.attachment_id, first_attachment)
        self.assertEqual(first_attachment.raw, b"first-package")
        self.assertTrue(second_attachment.exists())
        self.assertFalse(second_attachment.res_model)

    def test_publish_rejects_already_bound_attachment(self):
        skill = self._publish(self.owner_user, "bound", "Bound")
        with self.assertRaises(UserError):
            self.Tool.with_user(self.owner_user).skill_publish(
                skill.attachment_id.id, "bound2", "Second"
            )

    def test_publish_rejects_foreign_attachment(self):
        foreign = self._make_attachment(self.other_user, data=b"foreign")
        with self.assertRaises(AccessError):
            self.Tool.with_user(self.owner_user).skill_publish(
                foreign.id, "foreign", "Foreign"
            )

    def test_publish_rejects_empty_attachment(self):
        empty = self._make_attachment(self.owner_user, data=b"")
        with self.assertRaises(UserError):
            self.Tool.with_user(self.owner_user).skill_publish(
                empty.id, "empty", "Empty"
            )

    def test_publish_via_staged_upload(self):
        data = b"staged-bytes"
        FileTool = self.env["llm.mcp.file.tool"].with_user(self.owner_user)
        staged = FileTool.attachment_stage_upload("e2e.zip")
        attachment = self.env["ir.attachment"].browse(staged["attachment_id"])
        upload = self.env["llm.mcp.file.upload"].search(
            [("attachment_id", "=", attachment.id)]
        )
        attachment.sudo().write({"raw": data})
        upload.sudo().write({
            "state": "uploaded",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        })
        FileTool.attachment_commit_upload(attachment.id)

        skill = self._publish(
            self.owner_user, "e2e", "E2E", attachment=attachment
        )
        self.assertEqual(skill.attachment_id, attachment)
        self.assertEqual(attachment.res_model, "skillhub.skill")
        self.assertEqual(attachment.res_id, skill.id)

    # AC-4 -----------------------------------------------------------------

    def test_download_returns_url(self):
        skill = self._publish(self.owner_user, "dl", "Download")
        result = self.Tool.with_user(self.owner_user).skill_download(skill.id)
        self.assertIn("download", result)
        self.assertIn("curl", result)
        self.assertIn("/web/content/ir.attachment/", result["download"]["url"])
        self.assertIn("access_token=", result["download"]["url"])

    # AC-6 -----------------------------------------------------------------

    def test_read_isolation(self):
        skill = self._publish(self.owner_user, "iso", "ISO")
        self.assertTrue(
            self.env["skillhub.skill"].with_user(self.owner_user).search(
                [("id", "=", skill.id)]
            )
        )
        self.assertFalse(
            self.env["skillhub.skill"].with_user(self.plain_user).search(
                [("id", "=", skill.id)]
            )
        )
        self.Tool.with_user(self.owner_user).skill_share(
            skill.id, [self.shared_user.id]
        )
        self.assertTrue(
            self.env["skillhub.skill"].with_user(self.shared_user).search(
                [("id", "=", skill.id)]
            )
        )
        self.env["skillhub.skill"].with_user(self.owner_user).browse(skill.id).write(
            {"is_public": True}
        )
        self.assertTrue(
            self.env["skillhub.skill"].with_user(self.plain_user).search(
                [("id", "=", skill.id)]
            )
        )

    def test_admin_sees_and_can_edit_any_skill(self):
        skill = self._publish(self.owner_user, "admview", "Admin View")
        Skill = self.env["skillhub.skill"]

        self.assertTrue(
            Skill.with_user(self.other_user).search([("id", "=", skill.id)]),
            "an administrator should see every skill",
        )
        Skill.with_user(self.other_user).browse(skill.id).write(
            {"title": "Edited by admin"}
        )
        self.assertEqual(
            Skill.with_user(self.other_user).browse(skill.id).title,
            "Edited by admin",
        )
        self.assertIn(
            "download",
            self.Tool.with_user(self.other_user).skill_download(skill.id),
        )

    # AC-7 -----------------------------------------------------------------

    def test_share_owner_only(self):
        skill = self._publish(self.owner_user, "shr", "Share")
        self.Tool.with_user(self.owner_user).skill_share(
            skill.id, [self.shared_user.id]
        )
        with self.assertRaises(UserError):
            self.Tool.with_user(self.other_user).skill_share(
                skill.id, [self.shared_user.id]
            )

    # AC-8 -----------------------------------------------------------------

    def test_download_requires_access(self):
        skill = self._publish(self.owner_user, "dla", "Download Auth")
        with self.assertRaises(UserError):
            self.Tool.with_user(self.plain_user).skill_download(skill.id)
        self.Tool.with_user(self.owner_user).skill_share(
            skill.id, [self.shared_user.id]
        )
        self.assertIn(
            "download",
            self.Tool.with_user(self.shared_user).skill_download(skill.id),
        )
        self.env["skillhub.skill"].with_user(self.owner_user).browse(skill.id).write(
            {"is_public": True}
        )
        self.assertIn(
            "download",
            self.Tool.with_user(self.plain_user).skill_download(skill.id),
        )

    def test_plain_user_can_download_shared_skill(self):
        skill = self._publish(self.owner_user, "plaindl", "Plain Download")
        self.Tool.with_user(self.owner_user).skill_share(
            skill.id, [self.plain_user.id]
        )
        self.assertTrue(
            self.env["skillhub.skill"]
            .with_user(self.plain_user)
            .search([("id", "=", skill.id)]),
            "the shared skill should be readable before it is downloadable",
        )
        result = self.Tool.with_user(self.plain_user).skill_download(skill.id)
        self.assertIn("download", result)

    def test_plain_user_can_download_public_skill(self):
        skill = self._publish(self.owner_user, "plainpub", "Plain Public")
        self.env["skillhub.skill"].with_user(self.owner_user).browse(skill.id).write(
            {"is_public": True}
        )
        result = self.Tool.with_user(self.plain_user).skill_download(skill.id)
        self.assertIn("download", result)

    def test_plain_user_cannot_download_unshared_skill(self):
        skill = self._publish(self.owner_user, "plainno", "Plain No")
        with self.assertRaises(UserError):
            self.Tool.with_user(self.plain_user).skill_download(skill.id)

    # archive --------------------------------------------------------------

    def test_archive_owner_only_and_hides_from_active_search(self):
        skill = self._publish(self.owner_user, "arc", "Archive")
        self.Tool.with_user(self.owner_user).skill_archive(skill.id)
        self.assertEqual(
            self.env["skillhub.skill"].browse(skill.id).state, "archived"
        )
        self.assertFalse(
            self.env["skillhub.skill"].with_user(self.owner_user).search(
                [("state", "=", "active"), ("code", "=", "arc")]
            )
        )
        self.assertTrue(skill.attachment_id.exists())

    def test_skill_tools_registered(self):
        self.env["llm.tool"]._scan_tool_decorators()
        tools = {
            values["name"]: values
            for (_model, _method), values in self.env["llm.tool"]._tool_registry.items()
            if values["name"].startswith("skill_")
        }
        expected = {
            "skill_publish",
            "skill_download",
            "skill_share",
            "skill_unshare",
            "skill_archive",
        }
        self.assertTrue(expected.issubset(tools))
        for name in expected:
            self.assertEqual(tools[name]["code_group_xmlids"], '["base.group_user"]', name)

    def test_guide_contributed(self):
        guide = self.env["llm.tool.guide"].search([("code", "=", "skillhub")])
        self.assertTrue(guide)
        retriever = self.env["llm.tool.builtin.guide"]
        index = retriever.odoo_model_guide_retriever(query="skillhub")
        self.assertIn("skillhub", [g["code"] for g in index["guides"]])
        body = retriever.odoo_model_guide_retriever("skillhub")
        self.assertEqual(body["code"], "skillhub")
        self.assertIn("skill_publish", body["body"])
        self.assertIn("attachment_stage_upload", body["body"])
        self.assertIn("attachment_commit_upload", body["body"])
        self.assertIn("attachment_id", body["body"])
