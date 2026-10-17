import hashlib

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from psycopg2 import errors


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
        # Deliberately without the settings group. The storage ACLs hang off
        # that group, so an "administrator" test user sails straight through
        # permission checks a real shared user would be stopped by.
        cls.plain_user = cls._make_user("skill_plain", admin=False)

    @classmethod
    def _make_user(cls, login, admin=True):
        """A test user.

        ``admin=True`` adds ``base.group_system``, which every ``storage.*``
        model is ACL-bound to. Publishing needs it, so the users that publish
        keep it; anything asserting on the *permission boundary* has to pass
        ``admin=False`` or it proves nothing.
        """
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

    def _publish(self, user, code, title, description="", version="", data=b"zip-bytes", category_id=0, depends_on_ids=None):
        upload = self._stage_upload(user, data=data)
        result = self.Tool.with_user(user).skill_publish(
            upload.id, code, title, description=description, version=version,
            category_id=category_id, depends_on_ids=depends_on_ids,
        )
        return self.env["skillhub.skill"].browse(result["skill_id"])

    # AC-1 -----------------------------------------------------------------

    def test_model_fields(self):
        field_names = set(self.env["skillhub.skill"]._fields)
        expected = {
            "code", "title", "description", "version", "is_public",
            "shared_user_ids", "category_id", "backend_id", "storage_path",
            "size", "sha256", "depends_on_ids", "required_by_ids",
        }
        self.assertTrue(expected.issubset(field_names))

    def test_code_unique_and_slug(self):
        self._publish(self.owner_user, "dup", "Dup")
        with self.assertRaises(errors.UniqueViolation):
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
        self.assertTrue(self.backend.file_exists(skill.storage_path))

    def test_publish_updates_existing(self):
        first = self._publish(self.owner_user, "demo", "V1", version="1.0", data=b"v1")
        second = self._publish(self.owner_user, "demo", "V2", version="2.0", data=b"v2-long")
        self.assertEqual(first.id, second.id)
        skills = self.env["skillhub.skill"].search([("code", "=", "demo")])
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills.title, "V2")
        self.assertEqual(skills.size, len(b"v2-long"))

    def test_failed_publish_keeps_the_previous_blob(self):
        """A publish that fails after streaming the zip must not clobber it.

        The tool streams the new package onto the backend before it writes the
        record. If that write then fails, the bytes are already in place while
        the record -- and the ``sha256`` it carries -- stays on the previous
        version, so the stored checksum would end up describing a file that is
        no longer there. The old package is gone either way.
        """
        first = self._publish(self.owner_user, "atomic", "V1", data=b"first-package")
        with self.assertRaises(ValidationError):
            self._publish(
                self.owner_user,
                "atomic",
                "V2",
                data=b"second-package",
                depends_on_ids=[first.id],
            )
        with self.backend.open(first.storage_path, "rb") as stream:
            self.assertEqual(
                stream.read(),
                b"first-package",
                "the failed publish overwrote the package still referenced by "
                "the record",
            )

    # AC-4 -----------------------------------------------------------------

    def test_download_returns_url(self):
        skill = self._publish(self.owner_user, "dl", "Download")
        result = self.Tool.with_user(self.owner_user).skill_download(skill.id)
        self.assertIn("download", result)
        self.assertIn("curl", result)
        self.assertIn("/storage_mcp/t/", result["download"]["url"])

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

    def test_plain_user_can_download_shared_skill(self):
        """Sharing has to grant "take the file", not only "see the row".

        A shared user holds no settings group, so any lookup made under their
        own identity is refused by the storage ACLs -- which is exactly what
        ``skill_download`` used to do when it reached for ``skill.backend_id``.
        """
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
        """The other half: the fix must not turn this into a blank cheque.

        Reading the backend with elevated rights is only safe because the
        skill-level check already ran, so an unshared skill still has to be
        refused.
        """
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
                "skill_download",
                "skill_share",
                "skill_unshare",
                "skill_archive",
            }.issubset(names)
        )

    def test_guide_contributed(self):
        guide = self.env["llm.tool.guide"].search([("code", "=", "skillhub")])
        self.assertTrue(guide)
        retriever = self.env["llm.tool.builtin.guide"]
        index = retriever.odoo_model_guide_retriever(query="skillhub")
        self.assertIn("skillhub", [g["code"] for g in index["guides"]])
        body = retriever.odoo_model_guide_retriever("skillhub")
        self.assertEqual(body["code"], "skillhub")
        self.assertIn("skill_publish", body["body"])
        self.assertIn("odoo_record_retriever", body["body"])
