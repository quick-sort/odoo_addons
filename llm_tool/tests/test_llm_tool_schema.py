"""Tests for schema derivation and enforcement.

``input_schema`` is a stored column and the single source of truth: it is what
``execute()`` validates against, so it and what the LLM is shown can never
disagree.
"""

import json

from odoo.tests import tagged

from odoo.addons.llm_tool.models.llm_tool import (
    derive_input_schema,
    model_from_input_schema,
)

from .common import BUILTIN_MODEL, LLMToolCase


@tagged("post_install", "-at_install")
class TestSchemaDerivation(LLMToolCase):
    def test_derived_from_a_bound_method_excludes_self(self):
        method = getattr(self.env[BUILTIN_MODEL], "odoo_record_retriever")

        schema = derive_input_schema(method)

        self.assertNotIn("self", schema["properties"])
        self.assertEqual(
            set(schema["properties"]), {"model", "domain", "fields", "limit"}
        )
        self.assertEqual(schema["required"], ["model"])

    def test_derivation_failure_returns_none(self):
        self.assertIsNone(derive_input_schema("not a callable"))

    def test_stored_schema_wins_over_derivation(self):
        tool = self._manual_tool(
            name="stored_wins",
            input_schema='{"type": "object", "properties": {"only": {"type": "string"}}}',
        )

        self.assertEqual(set(tool.get_input_schema()["properties"]), {"only"})

    def test_empty_schema_falls_back_to_the_callable(self):
        """Only reachable for a code row created since the last scan."""
        tool = self.LLMTool.create(
            {
                "name": "fallback_probe",
                "source": "code",
                "executor": "model_method",
                "res_model": BUILTIN_MODEL,
                "res_method": "odoo_record_retriever",
            }
        )

        self.assertIn("limit", tool.get_input_schema()["properties"])

    def test_manual_row_with_no_callable_yields_an_empty_schema(self):
        tool = self._manual_tool(name="opaque", res_method="nonexistent")
        tool.invalidate_recordset()
        # get_input_schema reads the stored field first, so clear it.
        self.env.cr.execute(
            "UPDATE llm_tool SET input_schema = NULL WHERE id = %s", [tool.id]
        )
        tool.invalidate_recordset(["input_schema"])

        self.assertEqual(
            tool.get_input_schema(),
            {"type": "object", "properties": {}, "required": []},
        )

    def test_invalid_stored_json_raises(self):
        tool = self._manual_tool(name="bad_json", input_schema="not json {")

        with self.assertRaises(json.JSONDecodeError):
            tool.get_input_schema()

    def test_reset_rederives_for_code_rows(self):
        tool = self._builtin()
        tool.write({"input_schema": '{"type": "object", "properties": {}}'})

        tool.action_reset_input_schema()

        self.assertIn("limit", json.loads(tool.input_schema)["properties"])

    def test_reset_leaves_manual_rows_alone(self):
        narrow = '{"type": "object", "properties": {"model": {"type": "string"}}}'
        tool = self._manual_tool(name="reset_manual", input_schema=narrow)

        tool.action_reset_input_schema()

        self.assertEqual(json.loads(tool.input_schema), json.loads(narrow))


@tagged("post_install", "-at_install")
class TestSchemaCoercion(LLMToolCase):
    """``model_from_input_schema`` coerces rather than rejects.

    LLMs routinely send numbers and booleans as strings, and hallucinate extra
    arguments; a plain jsonschema validation would fail calls the tool would
    have accepted.
    """

    def _model(self, schema):
        return model_from_input_schema(schema)

    def test_numeric_string_is_coerced(self):
        model = self._model(
            {"type": "object", "properties": {"n": {"type": "integer"}}}
        )

        self.assertEqual(model(n="42").n, 42)

    def test_boolean_string_is_coerced(self):
        model = self._model(
            {"type": "object", "properties": {"b": {"type": "boolean"}}}
        )

        self.assertIs(model(b="true").b, True)

    def test_unknown_keys_are_dropped(self):
        model = self._model(
            {"type": "object", "properties": {"kept": {"type": "string"}}}
        )

        dumped = model(kept="a", hallucinated="b").model_dump(exclude_unset=True)

        self.assertEqual(dumped, {"kept": "a"})

    def test_required_key_is_enforced(self):
        model = self._model(
            {
                "type": "object",
                "properties": {"needed": {"type": "string"}},
                "required": ["needed"],
            }
        )

        with self.assertRaises(Exception):
            model()

    def test_optional_without_default_stays_unset(self):
        """So the callable's own Python default applies."""
        model = self._model(
            {"type": "object", "properties": {"opt": {"type": "string"}}}
        )

        self.assertEqual(model().model_dump(exclude_unset=True), {})

    def test_declared_default_is_used(self):
        model = self._model(
            {"type": "object", "properties": {"n": {"type": "integer", "default": 7}}}
        )

        self.assertEqual(model().n, 7)

    def test_unmappable_construct_degrades_to_any(self):
        """anyOf / $ref / missing type must not reject the call."""
        model = self._model(
            {
                "type": "object",
                "properties": {
                    "weird": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                    "untyped": {},
                },
            }
        )

        dumped = model(weird=[1, 2], untyped={"a": 1}).model_dump(exclude_unset=True)

        self.assertEqual(dumped, {"weird": [1, 2], "untyped": {"a": 1}})

    def test_nullable_union_takes_the_non_null_branch(self):
        model = self._model(
            {"type": "object", "properties": {"n": {"type": ["integer", "null"]}}}
        )

        self.assertEqual(model(n="5").n, 5)


@tagged("post_install", "-at_install")
class TestSchemaEnforcement(LLMToolCase):
    def test_execute_validates_against_the_stored_schema(self):
        """Not against the callable signature: narrowing must actually bite."""
        tool = self._manual_tool(
            name="enforced",
            input_schema='{"type": "object", "properties": '
            '{"model": {"type": "string"}}, "required": ["model"]}',
        )

        result = tool.execute({"model": "res.users", "limit": 1})

        # 'limit' was dropped, so the method's own default of 100 applied.
        self.assertGreaterEqual(len(result), 1)

    def test_missing_required_argument_fails(self):
        tool = self._manual_tool(name="needs_model")

        with self.assertRaises(Exception):
            tool.execute({})

    def test_stored_schema_matches_what_the_llm_is_shown(self):
        tool = self._builtin()

        definition = tool.get_tool_definition()

        self.assertEqual(definition["inputSchema"], tool.get_input_schema())
