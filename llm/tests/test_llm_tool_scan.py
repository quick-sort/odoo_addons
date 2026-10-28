"""Tests for the startup scan and its sync into ``source='code'`` rows.

Two phases, deliberately separate: ``_scan_tool_decorators`` walks
``env.registry`` into an in-memory dict with no DB access, then
``_sync_tools_to_db`` reconciles that dict with the ``source='code'`` rows using
raw SQL under an advisory lock.
"""

import json
from unittest.mock import patch

from odoo.tests import common, tagged

from .llm_tool_common import BUILTIN_METHOD, BUILTIN_MODEL


@tagged("post_install", "-at_install")
class TestScan(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LLMTool = cls.env["llm.tool"]

    def test_scan_finds_tools_on_abstract_models(self):
        """The built-ins live on abstract models, which are in env.registry."""
        self.LLMTool._scan_tool_decorators()

        self.assertIn(
            (BUILTIN_MODEL, BUILTIN_METHOD),
            self.LLMTool._tool_registry,
        )

    def test_scan_reads_metadata_off_the_decorator(self):
        self.LLMTool._scan_tool_decorators()
        values = self.LLMTool._tool_registry[(BUILTIN_MODEL, BUILTIN_METHOD)]

        self.assertEqual(values["executor"], "model_method")
        self.assertEqual(values["source"], "code")
        self.assertEqual(values["name"], BUILTIN_METHOD)
        self.assertTrue(values["description"])
        self.assertIn("model", json.loads(values["input_schema"])["properties"])
        self.assertTrue(values["read_only_hint"])

    def test_scan_does_no_db_write(self):
        """Phase one is pure in-memory; nothing reaches the database."""
        before = self.LLMTool.with_context(active_test=False).search_count([])

        self.LLMTool._scan_tool_decorators()

        self.assertEqual(
            self.LLMTool.with_context(active_test=False).search_count([]), before
        )

    def test_all_seven_builtins_are_scanned(self):
        self.LLMTool._scan_tool_decorators()
        scanned = {
            method
            for model, method in self.LLMTool._tool_registry
            if model.startswith("llm.tool.builtin.")
        }

        self.assertEqual(
            scanned,
            {
                "odoo_record_retriever",
                "odoo_record_creator",
                "odoo_record_updater",
                "odoo_record_unlinker",
                "odoo_model_method_executor",
                "odoo_model_inspector",
                "odoo_model_guide_retriever",
            },
        )


@tagged("post_install", "-at_install")
class TestSync(common.TransactionCase):
    """The registry is a class attribute, so patch the type, not the recordset."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LLMTool = cls.env["llm.tool"]

    def _set_registry(self, registry):
        patcher = patch.object(type(self.LLMTool), "_tool_registry", registry)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _values(self, name, model="res.partner", method="probe_method", **kwargs):
        values = {
            "name": name,
            "executor": "model_method",
            "source": "code",
            "res_model": model,
            "res_method": method,
            "description": "Scanned description",
            "title": "",
            "active": True,
        }
        values.update(kwargs)
        return values

    def test_creates_a_missing_row(self):
        self._set_registry({("res.partner", "probe_method"): self._values("probe_a")})

        result = self.LLMTool._sync_tools_to_db()
        self.LLMTool.invalidate_model()

        self.assertEqual(result["created"], 1)
        tool = self.LLMTool.search([("name", "=", "probe_a")])
        self.assertEqual(tool.source, "code")
        self.assertEqual(tool.res_method, "probe_method")

    def test_second_run_changes_nothing(self):
        self._set_registry({("res.partner", "probe_method"): self._values("probe_b")})
        self.LLMTool._sync_tools_to_db()
        self.LLMTool.invalidate_model()

        result = self.LLMTool._sync_tools_to_db()

        self.assertEqual(result, {"created": 0, "updated": 0, "deactivated": 0})

    def test_renaming_in_code_updates_the_row_in_place(self):
        """Keyed on the callable, never on the name.

        Keying on ``name`` would create a second row and archive the first, so
        agents referencing the old row would silently lose the tool.
        """
        self._set_registry({("res.partner", "probe_method"): self._values("old_name")})
        self.LLMTool._sync_tools_to_db()
        self.LLMTool.invalidate_model()
        original = self.LLMTool.search([("name", "=", "old_name")])

        self._set_registry({("res.partner", "probe_method"): self._values("new_name")})
        result = self.LLMTool._sync_tools_to_db()
        self.LLMTool.invalidate_model()

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 1)
        original.invalidate_recordset(["name"])
        self.assertEqual(original.name, "new_name")

    def test_archives_a_row_whose_method_disappeared(self):
        self._set_registry({("res.partner", "probe_method"): self._values("gone_soon")})
        self.LLMTool._sync_tools_to_db()
        self.LLMTool.invalidate_model()
        tool = self.LLMTool.search([("name", "=", "gone_soon")])

        # Still non-empty, otherwise the guard below short-circuits the sweep.
        self._set_registry({("res.partner", "other"): self._values("kept", method="other")})
        result = self.LLMTool._sync_tools_to_db()

        self.assertEqual(result["deactivated"], 1)
        tool.invalidate_recordset(["active"])
        self.assertFalse(tool.active)

    def test_empty_registry_archives_nothing(self):
        """An empty scan means "scan failed", not "no tools left"."""
        self._set_registry({("res.partner", "probe_method"): self._values("survivor")})
        self.LLMTool._sync_tools_to_db()
        self.LLMTool.invalidate_model()
        tool = self.LLMTool.search([("name", "=", "survivor")])

        self._set_registry({})
        result = self.LLMTool._sync_tools_to_db()

        self.assertEqual(result, {"created": 0, "updated": 0, "deactivated": 0})
        tool.invalidate_recordset(["active"])
        self.assertTrue(tool.active)

    def test_manual_rows_are_invisible_to_the_sync(self):
        """What makes a second, hand-narrowed exposure safe."""
        manual = self.LLMTool.create(
            {
                "name": "manual_exposure",
                "source": "manual",
                "executor": "model_method",
                "res_model": BUILTIN_MODEL,
                "res_method": BUILTIN_METHOD,
                "description": "hand written",
                "input_schema": '{"type": "object", "properties": {}}',
            }
        )
        # Same callable as the scanned entry below.
        self._set_registry(
            {(BUILTIN_MODEL, BUILTIN_METHOD): self._values(
                "scanned_one", model=BUILTIN_MODEL, method=BUILTIN_METHOD
            )}
        )

        self.LLMTool._sync_tools_to_db()
        manual.invalidate_recordset(["description", "name", "active"])

        self.assertEqual(manual.description, "hand written")
        self.assertEqual(manual.name, "manual_exposure")
        self.assertTrue(manual.active)

    def test_policy_flags_are_never_overwritten(self):
        self._set_registry({("res.partner", "probe_method"): self._values("policy_probe")})
        self.LLMTool._sync_tools_to_db()
        self.LLMTool.invalidate_model()
        tool = self.LLMTool.search([("name", "=", "policy_probe")])
        tool.write({"requires_user_consent": True, "is_default": True})

        self._set_registry(
            {("res.partner", "probe_method"): self._values(
                "policy_probe", description="changed"
            )}
        )
        self.LLMTool._sync_tools_to_db()
        tool.invalidate_recordset(["requires_user_consent", "is_default", "description"])

        self.assertTrue(tool.requires_user_consent)
        self.assertTrue(tool.is_default)
        self.assertEqual(tool.description, "changed")

    def test_annotations_are_synced(self):
        self._set_registry(
            {("res.partner", "probe_method"): self._values(
                "hint_probe", read_only_hint=True, destructive_hint=False,
                title="Synced Title",
            )}
        )
        self.LLMTool._sync_tools_to_db()
        self.LLMTool.invalidate_model()
        tool = self.LLMTool.search([("name", "=", "hint_probe")])

        self.assertTrue(tool.read_only_hint)
        self.assertFalse(tool.destructive_hint)
        self.assertEqual(tool.title, "Synced Title")

    def test_register_hook_runs_both_phases(self):
        self.LLMTool._register_hook()

        self.assertIsInstance(self.LLMTool._tool_registry, dict)
        self.assertTrue(self.LLMTool._tool_registry, "the built-ins must be found")


@tagged("post_install", "-at_install")
class TestSyncButton(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LLMTool = cls.env["llm.tool"]

    def test_warns_on_an_empty_registry(self):
        with patch.object(type(self.LLMTool), "_tool_registry", {}):
            result = self.LLMTool.action_sync_tools()

        self.assertEqual(result["params"]["type"], "warning")

    def test_reports_already_in_sync(self):
        result = self.LLMTool.action_sync_tools()

        self.assertIn(result["params"]["type"], ("info", "success"))


@tagged("post_install", "-at_install")
class TestSyncGroups(common.TransactionCase):
    """Declared groups are applied when the declaration changes, not every run."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LLMTool = cls.env["llm.tool"]

    def _set_registry(self, registry):
        patcher = patch.object(type(self.LLMTool), "_tool_registry", registry)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _values(self, name, **kwargs):
        values = {
            "name": name,
            "executor": "model_method",
            "source": "code",
            "res_model": "res.partner",
            "res_method": "probe_method",
            "description": "Scanned description",
            "title": "",
            "active": True,
            "code_group_xmlids": "",
        }
        values.update(kwargs)
        return values

    def _group(self, xml_name, group_name):
        group = self.env["res.groups"].create({"name": group_name})
        self.env["ir.model.data"].create(
            {
                "module": "llm_test_groups",
                "name": xml_name,
                "model": "res.groups",
                "res_id": group.id,
            }
        )
        return group, f"llm_test_groups.{xml_name}"

    def _decl(self, *xmlids):
        return json.dumps(sorted(xmlids))

    def _synced_tool(self, name):
        self.LLMTool.invalidate_model()
        return self.LLMTool.search([("name", "=", name)])

    def test_create_applies_declared_groups(self):
        group, xmlid = self._group("declared_a", "Declared Group A")
        self._set_registry(
            {
                ("res.partner", "probe_method"): self._values(
                    "group_probe_a", code_group_xmlids=self._decl(xmlid)
                )
            }
        )

        self.LLMTool._sync_tools_to_db()
        tool = self._synced_tool("group_probe_a")

        self.assertEqual(tool.allowed_group_ids, group)
        self.assertEqual(tool.code_group_xmlids, self._decl(xmlid))

    def test_declaration_change_replaces_the_set(self):
        group_a, xmlid_a = self._group("declared_a2", "Declared Group A2")
        group_b, xmlid_b = self._group("declared_b2", "Declared Group B2")
        key = ("res.partner", "probe_method")
        self._set_registry(
            {key: self._values("group_probe_b", code_group_xmlids=self._decl(xmlid_a))}
        )
        self.LLMTool._sync_tools_to_db()
        tool = self._synced_tool("group_probe_b")
        self.assertEqual(tool.allowed_group_ids, group_a)

        self._set_registry(
            {key: self._values("group_probe_b", code_group_xmlids=self._decl(xmlid_b))}
        )
        self.LLMTool._sync_tools_to_db()
        tool = self._synced_tool("group_probe_b")

        self.assertEqual(tool.allowed_group_ids, group_b)
        self.assertNotIn(group_a, tool.allowed_group_ids)

    def test_removing_the_declaration_clears_the_set(self):
        group_a, xmlid_a = self._group("declared_a3", "Declared Group A3")
        key = ("res.partner", "probe_method")
        self._set_registry(
            {key: self._values("group_probe_c", code_group_xmlids=self._decl(xmlid_a))}
        )
        self.LLMTool._sync_tools_to_db()
        tool = self._synced_tool("group_probe_c")
        self.assertEqual(tool.allowed_group_ids, group_a)

        self._set_registry({key: self._values("group_probe_c")})
        self.LLMTool._sync_tools_to_db()
        tool = self._synced_tool("group_probe_c")

        self.assertFalse(tool.allowed_group_ids)

    def test_hand_edited_groups_survive_an_unchanged_declaration(self):
        group_a, xmlid_a = self._group("declared_a4", "Declared Group A4")
        extra = self.env["res.groups"].create({"name": "Locally Added Group"})
        key = ("res.partner", "probe_method")
        values = {"name": "group_probe_d", "code_group_xmlids": self._decl(xmlid_a)}
        self._set_registry({key: self._values(**values)})
        self.LLMTool._sync_tools_to_db()
        tool = self._synced_tool("group_probe_d")
        tool.allowed_group_ids = [(4, extra.id)]

        self._set_registry({key: self._values(**values)})
        self.LLMTool._sync_tools_to_db()
        tool = self._synced_tool("group_probe_d")

        self.assertEqual(tool.allowed_group_ids, group_a | extra)

    def test_missing_xmlid_grants_nothing(self):
        self._set_registry(
            {
                ("res.partner", "probe_method"): self._values(
                    "group_probe_e",
                    code_group_xmlids=self._decl("nowhere.group_does_not_exist"),
                )
            }
        )

        self.LLMTool._sync_tools_to_db()
        tool = self._synced_tool("group_probe_e")

        self.assertFalse(tool.allowed_group_ids)
