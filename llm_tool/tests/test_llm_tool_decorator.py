"""Tests for ``@llm_tool``'s strictness.

The decorator is the only place metadata for a code-owned tool comes from, so it
refuses anything it cannot turn into a description or a schema. All three checks
are errors, not warnings: a tool the LLM cannot understand is worse than no tool.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.llm_tool.decorators import get_tool_metadata, is_llm_tool, llm_tool


@tagged("post_install", "-at_install")
class TestDecoratorValidation(TransactionCase):
    def test_missing_docstring_is_an_error(self):
        with self.assertRaises(ValueError) as ctx:

            @llm_tool
            def no_doc(self, x: str) -> dict:
                return {}

        self.assertIn("docstring", str(ctx.exception))

    def test_blank_docstring_is_an_error(self):
        with self.assertRaises(ValueError):

            @llm_tool
            def blank_doc(self, x: str) -> dict:
                """   """
                return {}

    def test_description_argument_replaces_the_docstring(self):
        @llm_tool(description="Given explicitly")
        def no_doc_but_described(self, x: str) -> dict:
            return {}

        self.assertEqual(
            get_tool_metadata(no_doc_but_described)["description"],
            "Given explicitly",
        )

    def test_missing_parameter_hint_is_an_error(self):
        with self.assertRaises(ValueError) as ctx:

            @llm_tool
            def no_hint(self, x) -> dict:
                """Has a docstring but no hint."""
                return {}

        self.assertIn("type hints", str(ctx.exception))

    def test_missing_return_hint_is_an_error(self):
        with self.assertRaises(ValueError) as ctx:

            @llm_tool
            def no_return(self, x: str):
                """Has a docstring and a param hint."""
                return {}

        self.assertIn("return type", str(ctx.exception))

    def test_explicit_schema_waives_the_hint_check(self):
        @llm_tool(schema={"type": "object", "properties": {"x": {"type": "string"}}})
        def legacy(self, x):
            """A legacy method without annotations."""
            return {}

        self.assertTrue(is_llm_tool(legacy))
        self.assertEqual(get_tool_metadata(legacy)["schema"]["type"], "object")

    def test_self_is_not_required_to_be_hinted(self):
        @llm_tool
        def fine(self, x: str) -> dict:
            """Only ``self`` is unannotated, which is expected."""
            return {}

        self.assertTrue(is_llm_tool(fine))


@tagged("post_install", "-at_install")
class TestDecoratorMetadata(TransactionCase):
    def test_name_defaults_to_the_function_name(self):
        @llm_tool
        def my_tool(self, x: str) -> dict:
            """Doc."""
            return {}

        self.assertEqual(get_tool_metadata(my_tool)["name"], "my_tool")

    def test_name_can_be_overridden(self):
        @llm_tool(name="renamed")
        def my_tool(self, x: str) -> dict:
            """Doc."""
            return {}

        self.assertEqual(get_tool_metadata(my_tool)["name"], "renamed")

    def test_annotations_pass_through_as_metadata(self):
        @llm_tool(read_only_hint=True, destructive_hint=False, title="Nice Title")
        def probe(self, x: str) -> dict:
            """Doc."""
            return {}

        metadata = get_tool_metadata(probe)["metadata"]

        self.assertTrue(metadata["read_only_hint"])
        self.assertFalse(metadata["destructive_hint"])
        self.assertEqual(metadata["title"], "Nice Title")

    def test_wrapper_keeps_the_signature_introspectable(self):
        """functools.wraps sets __wrapped__, so schema derivation still works."""
        import inspect

        @llm_tool
        def probe(self, alpha: str, beta: int = 3) -> dict:
            """Doc."""
            return {}

        params = list(inspect.signature(probe).parameters)

        self.assertEqual(params, ["self", "alpha", "beta"])

    def test_decorating_is_passive(self):
        """It tags the function; the startup scan is what registers it."""
        before = len(self.env["llm.tool"]._tool_registry)

        @llm_tool
        def probe(self, x: str) -> dict:
            """Doc."""
            return {}

        self.assertEqual(len(self.env["llm.tool"]._tool_registry), before)

    def test_xml_managed_is_gone(self):
        """Replaced by ``source='manual'`` on the row.

        It is swallowed by ``**metadata`` rather than rejected, so assert on the
        attribute the scan used to read instead of on a raise.
        """

        @llm_tool(xml_managed=True)
        def probe(self, x: str) -> dict:
            """Doc."""
            return {}

        self.assertFalse(hasattr(probe, "_llm_tool_xml_managed"))
