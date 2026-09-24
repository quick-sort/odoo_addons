import os

from lxml import etree

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSkillHubUI(TransactionCase):
    def test_ui_views_resolve(self):
        action = self.env.ref("skillhub.action_skillhub_skill")
        self.assertEqual(action.res_model, "skillhub.skill")
        self.assertEqual(action.view_mode, "list,form")
        self.assertEqual(
            action.search_view_id, self.env.ref("skillhub.view_skillhub_skill_search")
        )
        Skill = self.env["skillhub.skill"]
        for view in (
            self.env.ref("skillhub.view_skillhub_skill_list"),
            self.env.ref("skillhub.view_skillhub_skill_form"),
            self.env.ref("skillhub.view_skillhub_skill_search"),
        ):
            Skill.get_view(view_id=view.id, view_type=view.type)

    def test_list_blocks_create_delete(self):
        arch = etree.fromstring(self.env.ref("skillhub.view_skillhub_skill_list").arch)
        self.assertEqual(arch.get("create"), "false")
        self.assertEqual(arch.get("delete"), "false")

    def test_form_readonly_matrix(self):
        arch = etree.fromstring(self.env.ref("skillhub.view_skillhub_skill_form").arch)
        for name in ("code", "backend_id", "storage_path", "size", "sha256"):
            node = arch.xpath(f"//field[@name='{name}']")
            self.assertTrue(node, f"missing field {name}")
            self.assertEqual(node[0].get("readonly"), "1")
        for name in (
            "title",
            "description",
            "version",
            "is_public",
            "shared_user_ids",
            "state",
        ):
            node = arch.xpath(f"//field[@name='{name}']")
            self.assertTrue(node, f"missing field {name}")
            self.assertIsNone(node[0].get("readonly"))

    def test_menu_structure_and_icon(self):
        root = self.env.ref("skillhub.menu_skillhub_root")
        child = self.env.ref("skillhub.menu_skillhub_skill")
        self.assertFalse(root.action)
        self.assertEqual(child.parent_id, root)
        self.assertEqual(
            child.action, self.env.ref("skillhub.action_skillhub_skill")
        )
        self.assertEqual(root.web_icon, "skillhub,static/description/icon.svg")
        icon_path = os.path.join(
            get_module_path("skillhub"), "static", "description", "icon.svg"
        )
        self.assertTrue(os.path.isfile(icon_path), icon_path)
