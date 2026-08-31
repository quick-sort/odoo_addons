"""Tests for ``llm.tool`` as a registry: identity, source semantics, constraints.

The model used to carry a single ``implementation`` selection with nine mixed
values, half of them naming a strategy and half naming a concrete tool. It now
has two orthogonal axes: ``executor`` (how to run) and ``source`` (who owns the
metadata).
"""

import json

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import BUILTIN_METHOD, BUILTIN_MODEL, LLMToolCase


@tagged("post_install", "-at_install")
class TestRegistryShape(LLMToolCase):
    def test_executor_is_a_closed_set(self):
        """Three strategies, not one value per tool."""
        values = set(self.LLMTool._fields["executor"].get_values(self.env))

        self.assertLessEqual(values, {"model_method", "server_action", "mcp"})
        self.assertIn("model_method", values)

    def test_source_values(self):
        self.assertEqual(
            set(self.LLMTool._fields["source"].get_values(self.env)),
            {"code", "manual", "remote"},
        )

    def test_every_executor_has_a_handler(self):
        """``execute`` dispatches to ``_execute_<executor>``; none may be missing."""
        for executor in self.LLMTool._fields["executor"].get_values(self.env):
            self.assertTrue(
                hasattr(self.LLMTool, f"_execute_{executor}"),
                f"no _execute_{executor} for executor '{executor}'",
            )

    def test_removed_fields_are_gone(self):
        for gone in (
            "implementation",
            "auto_update",
            "decorator_model",
            "decorator_method",
            "mcp_tool_name",
        ):
            self.assertNotIn(gone, self.LLMTool._fields, f"{gone} still exists")

    def test_annotations_stay_real_booleans(self):
        """Not folded into a JSON blob: the list view filters on them.

        Their defaults also encode a safety policy -- destructive and open-world
        default to true, i.e. assume dangerous until declared otherwise.
        """
        for hint, default in (
            ("read_only_hint", False),
            ("idempotent_hint", False),
            ("destructive_hint", True),
            ("open_world_hint", True),
        ):
            field = self.LLMTool._fields[hint]
            self.assertEqual(field.type, "boolean")
            self.assertEqual(field.default(self.LLMTool), default, hint)


@tagged("post_install", "-at_install")
class TestIdentity(LLMToolCase):
    def test_tool_names_are_unique(self):
        self._manual_tool(name="dup_probe")

        with self.assertRaises(Exception), mute_logger("odoo.sql_db"):
            self._manual_tool(name="dup_probe")
            self.env.flush_all()

    def test_two_rows_may_expose_the_same_callable(self):
        """This is how one function gets exposed twice with different schemas."""
        wide = self._manual_tool(name="wide_retriever")
        narrow = self._manual_tool(
            name="narrow_retriever",
            input_schema='{"type": "object", "properties": '
            '{"model": {"type": "string"}}, "required": ["model"]}',
        )

        self.assertEqual(wide.res_model, narrow.res_model)
        self.assertEqual(wide.res_method, narrow.res_method)
        self.assertNotEqual(wide.id, narrow.id)


@tagged("post_install", "-at_install")
class TestSourceSemantics(LLMToolCase):
    def test_manual_row_requires_a_description(self):
        with self.assertRaises(ValidationError):
            self._manual_tool(name="no_desc", description=False)

    def test_manual_row_requires_a_schema(self):
        with self.assertRaises(ValidationError):
            self._manual_tool(name="no_schema", input_schema=False)

    def test_code_row_may_be_created_empty(self):
        """The scan fills it in afterwards, so creation must not demand it."""
        tool = self.LLMTool.create(
            {
                "name": "code_row_probe",
                "source": "code",
                "executor": "model_method",
                "res_model": BUILTIN_MODEL,
                "res_method": BUILTIN_METHOD,
            }
        )

        self.assertFalse(tool.description)

    def test_contract_source_only_for_code_rows(self):
        """``source`` is what decides whether metadata is derived at all."""
        code_row = self._builtin()
        manual_row = self._manual_tool(name="manual_no_contract")

        self.assertIsNotNone(code_row._contract_source())
        self.assertIsNone(manual_row._contract_source())

    def test_duplicate_as_manual_derives_an_editable_copy(self):
        builtin = self._builtin()

        action = builtin.action_duplicate_as_manual()
        copy = self.LLMTool.browse(action["res_id"])

        self.assertEqual(copy.source, "manual")
        self.assertEqual(copy.res_model, builtin.res_model)
        self.assertEqual(copy.res_method, builtin.res_method)
        self.assertEqual(copy.description, builtin.description)
        self.assertFalse(copy.is_default, "a copy must not double a default tool")

    def test_duplicated_copy_is_invisible_to_the_scan(self):
        builtin = self._builtin()
        copy = self.LLMTool.browse(builtin.action_duplicate_as_manual()["res_id"])
        copy.write({"description": "hand written", "input_schema": '{"type":"object"}'})

        self.LLMTool._sync_tools_to_db()
        copy.invalidate_recordset(["description", "input_schema"])

        self.assertEqual(copy.description, "hand written")


@tagged("post_install", "-at_install")
class TestExecutorConstraints(LLMToolCase):
    def test_model_method_needs_model_and_method(self):
        with self.assertRaises(ValidationError):
            self._manual_tool(name="incomplete", res_model=False)

    def test_server_action_needs_an_action(self):
        with self.assertRaises(ValidationError):
            self._manual_tool(name="no_action", executor="server_action")

    def test_missing_model_is_reported_clearly(self):
        tool = self._manual_tool(name="ghost_model", res_model="not.a.model")

        with self.assertRaises(UserError) as ctx:
            tool.execute({"model": "res.users"})

        self.assertIn("not.a.model", str(ctx.exception))

    def test_missing_method_is_reported_clearly(self):
        tool = self._manual_tool(name="ghost_method", res_method="no_such_method")

        with self.assertRaises(UserError) as ctx:
            tool.execute({"model": "res.users"})

        self.assertIn("no_such_method", str(ctx.exception))


@tagged("post_install", "-at_install")
class TestBuiltinTools(LLMToolCase):
    """The six built-ins are now decorated methods on abstract models."""

    EXPECTED = {
        "odoo_record_retriever": "llm.tool.builtin.records",
        "odoo_record_creator": "llm.tool.builtin.records",
        "odoo_record_updater": "llm.tool.builtin.records",
        "odoo_record_unlinker": "llm.tool.builtin.records",
        "odoo_model_method_executor": "llm.tool.builtin.method",
        "odoo_model_inspector": "llm.tool.builtin.inspector",
    }

    def test_each_builtin_is_registered_as_code(self):
        for method, model in self.EXPECTED.items():
            tool = self._builtin(method)
            self.assertTrue(tool, f"no code row for {method}")
            self.assertEqual(tool.executor, "model_method")
            self.assertEqual(tool.res_model, model)
            self.assertFalse(tool.res_id, "built-ins are model-level calls")

    def test_builtins_keep_their_xmlids(self):
        """llm_assistant references them, so the ids must survive."""
        for method in self.EXPECTED:
            ref = self.env.ref(f"llm_tool.llm_tool_{method}")
            self.assertEqual(ref.res_method, method)

    def test_description_comes_from_the_docstring(self):
        import inspect

        for method, model in self.EXPECTED.items():
            tool = self._builtin(method)
            expected = inspect.getdoc(getattr(self.env[model], method))
            self.assertEqual(tool.description, expected, method)

    def test_schema_comes_from_the_signature(self):
        for method in self.EXPECTED:
            schema = json.loads(self._builtin(method).input_schema)
            self.assertIn("model", schema["properties"], method)
            self.assertNotIn("self", schema["properties"], method)

    def test_policy_flags_stay_from_xml(self):
        """The scan owns metadata; consent and default stay the user's."""
        self.assertTrue(self._builtin("odoo_record_unlinker").requires_user_consent)
        self.assertFalse(self._builtin("odoo_record_retriever").requires_user_consent)

    def test_inspector_is_marked_read_only(self):
        self.assertTrue(self._builtin("odoo_model_inspector").read_only_hint)
        self.assertFalse(self._builtin("odoo_model_inspector").destructive_hint)
