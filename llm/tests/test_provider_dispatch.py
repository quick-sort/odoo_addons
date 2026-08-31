"""Tests for llm.provider service dispatch.

``llm.provider._dispatch`` resolves every contract on the adapter component
returned by ``_get_adapter()``; there is no ``<service>_<method>`` fallback on
the model any more.

The base ``llm`` addon ships no provider, so ``service`` has an empty selection.
The tests add a fake ``dispatch_probe`` value to the field for their duration
(see ``selection_value``) and attach the implementations they need with
``mock.patch.object(..., create=True)``.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import common, tagged

from odoo.addons.component.core import Component
from odoo.addons.component.exception import SeveralComponentError
from odoo.addons.component.tests.common import TransactionComponentRegistryCase
from odoo.addons.llm.tests.common import selection_value

FAKE_SERVICE = "dispatch_probe"


class _StubAdapter:
    """Minimal adapter: only implements part of the service contract."""

    def __init__(self):
        self.calls = []

    def chat(self, provider, *args, **kwargs):
        self.calls.append(("chat", provider, args, kwargs))
        return "from-adapter"

    def test_model(self, provider, model):
        self.calls.append(("test_model", provider, model))
        return {"state": "success", "message": "stub", "detail": ""}


@tagged("post_install", "-at_install")
class TestProviderDispatch(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Provider = cls.env["llm.provider"]
        cls.ProviderClass = type(cls.Provider)

    def setUp(self):
        super().setUp()
        # Make FAKE_SERVICE a valid value of the ``service`` selection for the
        # whole test, so the record stays writable. The field is a static list
        # extended with ``selection_add``, so this patches the field itself --
        # patching a model method would no longer have any effect.
        fake_service = selection_value(
            self.Provider, "service", FAKE_SERVICE, "Dispatch Probe"
        )
        fake_service.__enter__()
        self.addCleanup(fake_service.__exit__, None, None, None)

        self.provider = self.Provider.create(
            {"name": "Dispatch Probe Provider", "service": FAKE_SERVICE},
        )

    def _patch_provider(self, attr, value):
        """Attach ``attr`` to llm.provider for the duration of the test."""
        attr_patch = patch.object(self.ProviderClass, attr, value, create=True)
        attr_patch.start()
        self.addCleanup(attr_patch.stop)

    def _use_adapter(self, adapter):
        self._patch_provider("_get_adapter", lambda records: adapter)
        return adapter

    # ------------------------------------------------------------------
    # Preconditions
    # ------------------------------------------------------------------

    def test_missing_service_raises_user_error(self):
        provider = self.Provider.new({"name": "No service"})
        with self.assertRaises(UserError):
            provider._dispatch("chat")

    def test_missing_adapter_raises_user_error(self):
        """A service with no registered adapter is a configuration problem."""
        self._patch_provider("_get_adapter", lambda records: None)

        with self.assertRaises(UserError):
            self.provider._dispatch("chat")

    def test_method_absent_from_the_adapter_raises_not_implemented(self):
        self._use_adapter(_StubAdapter())  # implements chat and test_model only

        with self.assertRaises(NotImplementedError):
            self.provider._dispatch("embedding")

    # ------------------------------------------------------------------
    # Adapter dispatch
    # ------------------------------------------------------------------

    def test_dispatch_calls_the_adapter(self):
        adapter = self._use_adapter(_StubAdapter())

        self.assertEqual(self.provider._dispatch("chat"), "from-adapter")
        self.assertEqual(len(adapter.calls), 1)

    def test_adapter_receives_provider_as_first_argument(self):
        adapter = self._use_adapter(_StubAdapter())

        self.provider._dispatch("chat", "hello", stream=False)

        name, provider, args, kwargs = adapter.calls[0]
        self.assertEqual(name, "chat")
        self.assertEqual(provider, self.provider)
        self.assertEqual(args, ("hello",))
        self.assertEqual(kwargs, {"stream": False})

    def test_dispatch_requires_a_singleton(self):
        """Dispatch reads self.service first, so multi-record recordsets raise.

        Documents a pre-existing constraint rather than a new one: the very
        first statement of ``_dispatch`` reads a field, and Odoo raises on
        field access over several records.
        """
        other = self.Provider.create(
            {"name": "Second probe", "service": FAKE_SERVICE},
        )
        pair = self.provider | other
        self.assertEqual(len(pair), 2)

        with self.assertRaises(ValueError):
            pair._dispatch("chat")

    # ------------------------------------------------------------------
    # Optional capability probing
    # ------------------------------------------------------------------

    def test_has_service_method_sees_adapter_method(self):
        self._use_adapter(_StubAdapter())

        self.assertTrue(self.provider._has_service_method("test_model"))
        self.assertTrue(self.provider._has_service_method("chat"))
        self.assertFalse(self.provider._has_service_method("embedding"))

    def test_has_service_method_without_service(self):
        provider = self.Provider.new({"name": "No service"})

        self.assertFalse(provider._has_service_method("chat"))

    # ------------------------------------------------------------------
    # Contract declaration stays in sync with the base entry points
    # ------------------------------------------------------------------

    def test_service_contract_covers_dispatched_methods(self):
        """Every contract dispatched by the base model must be declared."""
        dispatched = {
            "get_client",
            "normalize_prepend_messages",
            "chat",
            "embedding",
            "generate",
            "models",
            "format_tools",
            "format_messages",
            "test_model",
            "determine_model_use",
        }

        self.assertEqual(set(self.Provider._SERVICE_CONTRACT), dispatched)



@tagged("post_install", "-at_install")
class TestProviderAdapterLookup(TransactionComponentRegistryCase):
    """Exercise the real component resolution done by ``_get_adapter``.

    Uses an isolated component registry so the stub adapters below never reach
    the database-wide registry. The stubs are declared inside the tests rather
    than at module level: ``MetaComponent`` registers a component class at
    import time, and a module-level declaration would sit in
    ``MetaComponent._modules_components["llm"]`` for the rest of the process.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ProviderClass = type(cls.env["llm.provider"])

    def setUp(self):
        super().setUp()
        self._setup_registry(self)
        self.addCleanup(self._teardown_registry, self)
        # llm is the addon under test, so _setup_registry excluded it: load its
        # components explicitly to get the llm.provider.adapter abstract base.
        self._load_module_components("llm")

        fake_service = selection_value(
            self.env["llm.provider"], "service", FAKE_SERVICE, "Dispatch Probe"
        )
        fake_service.__enter__()
        self.addCleanup(fake_service.__exit__, None, None, None)

        # Built after _setup_registry so the record's env carries the
        # components_registry context key that work_on() propagates.
        self.provider = self.env["llm.provider"].create(
            {"name": "Adapter Lookup Provider", "service": FAKE_SERVICE},
        )

    def _build_stub(self, name, usage, chat_result="from-component"):
        class _StubComponent(Component):
            _name = name
            _inherit = "llm.provider.adapter"
            _usage = usage

            def chat(self, provider, *args, **kwargs):
                return chat_result

        self._build_components(_StubComponent)
        return _StubComponent

    def test_no_component_returns_none(self):
        """An unmigrated service resolves to no adapter, not an exception."""
        self.assertIsNone(self.provider._get_adapter())

    def test_component_matching_service_is_returned(self):
        self._build_stub("stub.provider.adapter", FAKE_SERVICE)

        adapter = self.provider._get_adapter()

        self.assertIsNotNone(adapter)
        self.assertEqual(adapter._usage, FAKE_SERVICE)
        self.assertEqual(adapter._collection, "llm.provider")

    def test_dispatch_routes_to_the_component(self):
        self._build_stub("stub.provider.adapter", FAKE_SERVICE)

        self.assertEqual(self.provider._dispatch("chat"), "from-component")

    def test_component_of_another_service_is_not_used(self):
        self._build_stub("stub.other.adapter", "some_other_service")

        self.assertIsNone(self.provider._get_adapter())

    def test_duplicate_usage_propagates(self):
        """Two adapters for one service is a deployment error, not a fallback."""
        self._build_stub("stub.provider.adapter.a", FAKE_SERVICE)
        self._build_stub("stub.provider.adapter.b", FAKE_SERVICE)

        with self.assertRaises(SeveralComponentError):
            self.provider._get_adapter()

    def test_mandatory_contracts_are_declared_on_the_base(self):
        """Mandatory contracts belong on the abstract base.

        Declaring them documents the signature where it is implemented and
        turns a misspelled override into an unimplemented method instead of an
        AttributeError at call time.
        """
        self._build_stub("stub.provider.adapter", FAKE_SERVICE)
        adapter = self.provider._get_adapter()
        Provider = self.env["llm.provider"]

        missing = [
            name
            for name in Provider._SERVICE_CONTRACT
            if name not in Provider._OPTIONAL_SERVICE_CONTRACT
            and not hasattr(adapter, name)
        ]

        self.assertFalse(
            missing,
            "llm.provider.adapter must declare every mandatory contract, "
            "missing: %s" % missing,
        )

    def test_optional_contracts_are_absent_from_the_base(self):
        """Optional contracts must stay undeclared, or their fallback dies.

        ``llm.provider`` probes them with ``_has_service_method`` and falls back
        to service-agnostic behaviour. A stub on the base -- even one that only
        raises ``NotImplementedError`` -- makes ``hasattr`` true for every
        adapter, so the fallback would never run.
        """
        self._build_stub("stub.provider.adapter", FAKE_SERVICE)
        adapter = self.provider._get_adapter()
        Provider = self.env["llm.provider"]

        self.assertTrue(
            Provider._OPTIONAL_SERVICE_CONTRACT,
            "llm.provider is expected to have optional contracts",
        )

        declared = [
            name
            for name in Provider._OPTIONAL_SERVICE_CONTRACT
            if hasattr(adapter, name)
        ]

        self.assertFalse(
            declared,
            "llm.provider.adapter must not declare optional contracts, "
            "found: %s" % declared,
        )

    def test_optional_contracts_are_a_subset_of_the_contract(self):
        Provider = self.env["llm.provider"]

        self.assertLessEqual(
            Provider._OPTIONAL_SERVICE_CONTRACT,
            set(Provider._SERVICE_CONTRACT),
        )

    def test_optional_contracts_are_probed_as_absent(self):
        """An optional contract is only meaningful if the probe reports it missing.

        The stub inherits ``llm.provider.adapter`` and overrides only ``chat``,
        so this is exactly the situation the fallbacks exist for.
        """
        self._build_stub("stub.provider.adapter", FAKE_SERVICE)
        Provider = self.env["llm.provider"]

        for name in Provider._OPTIONAL_SERVICE_CONTRACT:
            self.assertFalse(
                self.provider._has_service_method(name),
                f"'{name}' is declared optional but the probe already sees it, "
                f"so its fallback is unreachable",
            )

    def test_mandatory_contracts_are_probed_as_present(self):
        """The flip side: declaring them makes the probe report them."""
        self._build_stub("stub.provider.adapter", FAKE_SERVICE)
        Provider = self.env["llm.provider"]

        for name in Provider._SERVICE_CONTRACT:
            if name in Provider._OPTIONAL_SERVICE_CONTRACT:
                continue
            self.assertTrue(self.provider._has_service_method(name))

    def test_missing_determine_model_use_falls_back_to_generic_rules(self):
        """The fallback this split protects, exercised end to end."""
        self._build_stub("stub.provider.adapter", FAKE_SERVICE)

        self.assertEqual(
            self.provider._determine_model_use("text-embedding-3-small", []),
            "embedding",
        )

    def test_undeclared_mandatory_contract_raises_not_implemented(self):
        """The stub inherits the base, so a contract it skips still fails loudly."""
        self._build_stub("stub.provider.adapter", FAKE_SERVICE)

        with self.assertRaises(NotImplementedError):
            self.provider._dispatch("embedding", ["text"])
