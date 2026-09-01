"""Tests for the ``llm.store`` adapter contract.

Reads the abstract base component straight out of the component registry, so no
store service has to be registered.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.component.core import _component_databases

#: Methods every ``llm.store.adapter`` must implement, dispatched by the base
#: model. Hardcoded here rather than read off a class attribute: the contract
#: lives in the code (the base component's stubs, and the model's
#: ``_dispatch`` call sites), not in a separate declaration. Unlike
#: ``llm.provider``, none of these is probed with ``_has_service_method``
#: before dispatch -- there is no optional contract on ``llm.store``.
MANDATORY_CONTRACT = (
    "create_collection",
    "delete_collection",
    "list_collections",
    "collection_exists",
    "sanitize_collection_name",
    "insert_vectors",
    "delete_vectors",
    "search_vectors",
    "create_index",
)


@tagged("post_install", "-at_install")
class TestStoreContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Store = cls.env["llm.store"]
        registry = _component_databases[cls.env.cr.dbname]
        cls.adapter_cls = registry["llm.store.adapter"]

    def test_every_contract_is_declared_on_the_base(self):
        missing = [
            name for name in MANDATORY_CONTRACT if not hasattr(self.adapter_cls, name)
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
        adapter = object.__new__(self.adapter_cls)

        with self.assertRaises(NotImplementedError):
            adapter.sanitize_collection_name(self.Store, "probe")
