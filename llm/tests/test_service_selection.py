"""Tests for the static service selections and their uninstall policy.

``llm.provider.service``, ``llm.store.service`` and ``llm.tool.executor``
moved from ``selection=lambda self: self._selection_service()`` to a static
``selection`` extended by each addon with ``selection_add``.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service

from .common import selection_value

DISPATCH_MODELS = [
    ("llm.provider", "service"),
    ("llm.store", "service"),
    ("llm.tool", "executor"),
]


@tagged("post_install", "-at_install")
class TestServiceSelection(TransactionCase):
    def _field(self, model_name, field_name):
        return type(self.env[model_name])._fields[field_name]

    def _installed(self, model_name):
        return model_name in self.env

    # ------------------------------------------------------------------
    # The property that did not hold before: values are validated
    # ------------------------------------------------------------------

    def test_unknown_service_is_rejected(self):
        """With ``selection=lambda`` this silently stored any string.

        ``Selection._selection`` stays ``None`` for a callable selection, so
        ``convert_to_cache`` skipped the membership check entirely and a typo in
        ``service`` only surfaced later as "no adapter registered".
        """
        with self.assertRaises(ValueError):
            self.env["llm.provider"].create(
                {"name": "typo", "service": "openia"}
            )

    def test_unknown_executor_is_rejected(self):
        with self.assertRaises(ValueError):
            self.env["llm.tool"].create(
                {"name": "typo_tool", "executor": "model_methd"}
            )

    def test_selection_is_static_on_every_dispatch_model(self):
        """A callable selection would silently disable write validation."""
        for model_name, field_name in DISPATCH_MODELS:
            if not self._installed(model_name):
                continue
            field = self._field(model_name, field_name)

            self.assertIsInstance(
                field.selection,
                list,
                f"{model_name}.{field_name} must use a static selection",
            )
            self.assertIsNotNone(
                field._selection,
                f"{model_name}.{field_name} is not validated on write",
            )

    # ------------------------------------------------------------------
    # ondelete: required + selection_add forces an explicit policy
    # ------------------------------------------------------------------

    def test_every_added_value_declares_an_ondelete_policy(self):
        """Odoo rejects 'set null' on a required field, and these are required.

        The policy must therefore be explicit for each contributed value.
        """
        for model_name, field_name in DISPATCH_MODELS:
            if not self._installed(model_name):
                continue
            field = self._field(model_name, field_name)
            self.assertTrue(field.required, f"{model_name}.{field_name}")

            for value in field.get_values(self.env):
                policy = (field.ondelete or {}).get(value)
                if policy is None:
                    # Declared in the base addon's own static list, so it
                    # disappears only when the model itself does.
                    continue
                self.assertNotEqual(
                    policy,
                    "set null",
                    f"{model_name}.{field_name}[{value}] would blank a "
                    f"required field on uninstall",
                )

    def test_contributed_values_archive_rather_than_cascade(self):
        """Uninstalling an addon must not destroy provider configuration.

        ``llm.model.provider_id`` is ``ondelete="cascade"``, so a ``cascade``
        policy here would take every model of that provider with it.
        """
        field = self._field("llm.provider", "service")

        for value, policy in (field.ondelete or {}).items():
            self.assertIs(
                policy,
                archive_dangling_service,
                f"llm.provider.service[{value}] uses {policy!r}",
            )

    def test_archive_policy_archives_and_keeps_the_record(self):
        with selection_value(self.env["llm.provider"], "service", "probe_svc"):
            provider = self.env["llm.provider"].create(
                {"name": "archive probe", "service": "probe_svc"}
            )

            archive_dangling_service(provider)

            self.assertFalse(provider.active)
            self.assertTrue(provider.exists(), "record must survive")
            self.assertEqual(provider.service, "probe_svc", "value is kept")

    def test_archive_policy_tolerates_an_empty_recordset(self):
        archive_dangling_service(self.env["llm.provider"])

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------

    def test_labels_are_translatable(self):
        """Static selections get ir.model.fields.selection rows; callables don't.

        ``_description_selection`` looks translations up there, so with the old
        dynamic selection the labels could never be translated.
        """
        rows = self.env["ir.model.fields.selection"].search(
            [
                ("field_id.model", "=", "llm.tool"),
                ("field_id.name", "=", "executor"),
            ]
        )

        self.assertTrue(rows, "no selection rows registered for llm.tool")
        self.assertIn("model_method", rows.mapped("value"))

    def test_dynamic_selection_hooks_are_gone(self):
        """Two mechanisms for one selection is what this change removed."""
        for model_name, hook in (
            ("llm.provider", "_get_available_services"),
            ("llm.store", "_get_available_services"),
            ("llm.tool", "_get_available_implementations"),
        ):
            if not self._installed(model_name):
                continue
            self.assertFalse(
                hasattr(self.env[model_name], hook),
                f"{model_name}.{hook} still exists alongside selection_add",
            )
