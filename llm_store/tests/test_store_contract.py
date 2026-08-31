"""Tests for the ``llm.store`` adapter contract split.

Reads the abstract base component straight out of the component registry, so no
store service has to be registered.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.component.core import _component_databases


@tagged("post_install", "-at_install")
class TestStoreContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Store = cls.env["llm.store"]
        registry = _component_databases[cls.env.cr.dbname]
        cls.adapter_cls = registry["llm.store.adapter"]

    def test_no_store_contract_is_optional(self):
        """Nothing on ``llm.store`` is probed, so nothing may be optional.

        If a fallback is ever added for one of these, it has to be listed in
        ``_OPTIONAL_SERVICE_CONTRACT`` *and* removed from
        ``llm.store.adapter``, or the fallback will be dead on arrival.
        """
        self.assertEqual(self.Store._OPTIONAL_SERVICE_CONTRACT, frozenset())

    def test_every_contract_is_declared_on_the_base(self):
        missing = [
            name
            for name in self.Store._SERVICE_CONTRACT
            if not hasattr(self.adapter_cls, name)
        ]

        self.assertFalse(
            missing,
            "llm.store.adapter must declare every contract, missing: %s" % missing,
        )

    def test_declared_stubs_raise_not_implemented(self):
        """An adapter omitting a contract must fail loudly, not silently."""
        adapter = object.__new__(self.adapter_cls)

        with self.assertRaises(NotImplementedError):
            adapter.list_collections(self.Store)

    def test_sanitize_collection_name_is_mandatory(self):
        """It is dispatched unconditionally, despite the default helper.

        ``_default_sanitize_collection_name`` is a helper an adapter may call,
        not a fallback the model applies -- so a store that omits
        ``sanitize_collection_name`` breaks rather than degrading.
        """
        self.assertIn("sanitize_collection_name", self.Store._SERVICE_CONTRACT)
        self.assertNotIn(
            "sanitize_collection_name", self.Store._OPTIONAL_SERVICE_CONTRACT
        )
