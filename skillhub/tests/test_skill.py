import hashlib

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSkillHub(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env.ref("storage_backend.default_storage_backend")
        cls.backend.mcp_read_enabled = True
        cls.backend.mcp_write_enabled = True
        cls.Tool = cls.env["skillhub.tool"]
        cls.main_company = cls.env.ref("base.main_company")
        cls.owner_user = cls._make_user("skill_owner")
        cls.other_user = cls._make_user("skill_other")
        cls.shared_user = cls._make_user("skill_shared")

    @classmethod
    def _make_user(cls, login):
        group_ids = [
            cls.env.ref("base.group_user").id,
            cls.env.ref("base.group_system").id,
        ]
        return cls.env["res.users"].create({
            "name": login,
            "login": login,
            "company_id": cls.main_company.id,
            "company_ids": [Command.set([cls.main_company.id])],
            "group_ids": [Command.set(group_ids)],
        })

    def _stage_upload(self, user, data=b"zip-bytes", name="skill.zip"):
        upload = self.env["storage.upload"].with_user(user).create({
            "name": name,
            "backend_id": self.backend.id,
            "relative_path": self.env["storage.upload"]._stage_path(name),
        })
        with self.backend.open(upload.relative_path, "wb") as f:
            f.write(data)
        upload.with_user(user).commit()
        return upload

    def _publish(self, user, code, title, description="", version="", data=b"zip-bytes"):
        upload = self._stage_upload(user, data=data)
        result = self.Tool.with_user(user).skill_publish(
            upload.id, code, title, description=description, version=version
        )
        return self.env["skillhub.skill"].browse(result["skill_id"])

    def _search_codes(self, user, query):
        return sorted(
            item["code"] for item in self.Tool.with_user(user).skill_search(query)
        )

    # AC-1 -----------------------------------------------------------------

    def test_model_fields(self):
        field_names = set(self.env["skillhub.skill"]._fields)
        expected = {
            "code", "title", "description", "version", "is_public",
            "shared_user_ids", "backend_id", "storage_path", "size", "sha256",
        }
        self.assertTrue(expected.issubset(field_names))

    def test_code_unique_and_slug(self):
        self._publish(self.owner_user, "dup", "Dup")
        with self.assertRaises(ValidationError):
            self.env["skillhub.skill"].create({
                "code": "dup",
                "title": "X",
                "backend_id": self.backend.id,
                "storage_path": "skillhub/dup.zip",
            })
        with self.assertRaises(UserError):
            self.Tool.with_user(self.owner_user).skill_publish(
                self._stage_upload(self.owner_user).id,
                "bad/code",
                "Bad Code",
            )

    # AC-2 / AC-3 ----------------------------------------------------------

    def test_publish_creates_skill(self):
        data = b"hello-skill"
        skill = self._publish(self.owner_user, "demo", "Demo Skill", data=data)
        self.assertEqual(skill.code, "demo")
        self.assertEqual(skill.size, len(data))
        self.assertEqual(skill.sha256, hashlib.sha256(data).hexdigest())
        self.assertTrue(self.backend.file_exists(skill.storage_path))

    def test_publish_updates_existing(self):
        first = self._publish(self.owner_user, "demo", "V1", version="1.0", data=b"v1")
        second = self._publish(self.owner_user, "demo", "V2", version="2.0", data=b"v2-long")
        self.assertEqual(first.id, second.id)
        skills = self.env["skillhub.skill"].search([("code", "=", "demo")])
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills.title, "V2")
        self.assertEqual(skills.size, len(b"v2-long"))

    # AC-4 -----------------------------------------------------------------

    def test_download_returns_url(self):
        skill = self._publish(self.owner_user, "dl", "Download")
        result = self.Tool.with_user(self.owner_user).skill_download(skill.id)
        self.assertIn("download", result)
        self.assertIn("curl", result)
        self.assertIn("/storage_mcp/t/", result["download"]["url"])

    # AC-5 -----------------------------------------------------------------

    def test_search_by_name_and_description(self):
        self._publish(self.owner_user, "alpha", "Alpha Skill", description="parses text")
        self._publish(self.owner_user, "beta", "Beta Skill", description="does other")
        self.assertEqual(self._search_codes(self.owner_user, "alp"), ["alpha"])
        self.assertEqual(self._search_codes(self.owner_user, "Beta"), ["beta"])
        self.assertEqual(self._search_codes(self.owner_user, "parses"), ["alpha"])

    # AC-6 -----------------------------------------------------------------

    def test_read_isolation(self):
        skill = self._publish(self.owner_user, "iso", "ISO")
        self.assertTrue(
            self.env["skillhub.skill"].with_user(self.owner_user).search(
                [("id", "=", skill.id)]
            )
        )
        self.assertFalse(
            self.env["skillhub.skill"].with_user(self.other_user).search(
                [("id", "=", skill.id)]
            )
        )
        self.Tool.with_user(self.owner_user).skill_share(skill.id, [self.shared_user.id])
        self.assertTrue(
            self.env["skillhub.skill"].with_user(self.shared_user).search(
                [("id", "=", skill.id)]
            )
        )
        self.env["skillhub.skill"].with_user(self.owner_user).browse(skill.id).write(
            {"is_public": True}
        )
        self.assertTrue(
            self.env["skillhub.skill"].with_user(self.other_user).search(
                [("id", "=", skill.id)]
            )
        )

    # AC-7 -----------------------------------------------------------------

    def test_share_owner_only(self):
        skill = self._publish(self.owner_user, "shr", "Share")
        self.Tool.with_user(self.owner_user).skill_share(skill.id, [self.other_user.id])
        with self.assertRaises(UserError):
            self.Tool.with_user(self.other_user).skill_share(
                skill.id, [self.shared_user.id]
            )

    # AC-8 -----------------------------------------------------------------

    def test_download_requires_access(self):
        skill = self._publish(self.owner_user, "dla", "Download Auth")
        with self.assertRaises(UserError):
            self.Tool.with_user(self.other_user).skill_download(skill.id)
        self.Tool.with_user(self.owner_user).skill_share(skill.id, [self.shared_user.id])
        self.assertIn(
            "download",
            self.Tool.with_user(self.shared_user).skill_download(skill.id),
        )
        self.env["skillhub.skill"].with_user(self.owner_user).browse(skill.id).write(
            {"is_public": True}
        )
        self.assertIn(
            "download",
            self.Tool.with_user(self.other_user).skill_download(skill.id),
        )

    # archive --------------------------------------------------------------

    def test_archive_owner_only_and_hides_from_search(self):
        skill = self._publish(self.owner_user, "arc", "Archive")
        self.Tool.with_user(self.owner_user).skill_archive(skill.id)
        self.assertEqual(
            self.env["skillhub.skill"].browse(skill.id).state, "archived"
        )
        self.assertEqual(self._search_codes(self.owner_user, "arc"), [])

    def test_skill_tools_registered(self):
        self.env["llm.tool"]._scan_tool_decorators()
        names = {
            values["name"]
            for (model, method), values in self.env["llm.tool"]._tool_registry.items()
            if values["name"].startswith("skill_")
        }
        self.assertTrue(
            {
                "skill_publish",
                "skill_search",
                "skill_get",
                "skill_download",
                "skill_share",
                "skill_unshare",
                "skill_archive",
            }.issubset(names)
        )
