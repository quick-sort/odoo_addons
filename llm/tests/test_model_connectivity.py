"""Tests for ``llm.model.test_model``: routed on ``model_use``, not on the adapter.

Connectivity testing dispatches to this model's own ``chat``/``embedding``/
``generate`` methods -- the same ones any other caller would use it through --
never to a provider-side ``test_model`` (there is none any more).
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.component.core import Component
from odoo.addons.component.tests.common import TransactionComponentRegistryCase

from .common import selection_value

FAKE_SERVICE = "connectivity_probe"


@tagged("post_install", "-at_install")
class TestModelConnectivity(TransactionComponentRegistryCase):
    """Exercises real component resolution, like ``test_provider_dispatch.py``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self._setup_registry(self)
        self.addCleanup(self._teardown_registry, self)
        self._load_module_components("llm")

        fake_service = selection_value(
            self.env["llm.provider"], "service", FAKE_SERVICE, "Connectivity Probe"
        )
        fake_service.__enter__()
        self.addCleanup(fake_service.__exit__, None, None, None)

        self.provider = self.env["llm.provider"].create(
            {"name": "Connectivity Probe Provider", "service": FAKE_SERVICE},
        )

    def _model(self, model_use, **kwargs):
        values = {
            "name": "probe-model",
            "provider_id": self.provider.id,
            "model_use": model_use,
        }
        values.update(kwargs)
        return self.env["llm.model"].create(values)

    def _build_stub(self, **methods):
        class _StubComponent(Component):
            _name = "stub.connectivity.adapter"
            _inherit = "llm.provider.adapter"
            _usage = FAKE_SERVICE

            def normalize_prepend_messages(self, provider, prepend_messages):
                return prepend_messages or []

        for name, impl in methods.items():
            setattr(_StubComponent, name, impl)

        self._build_components(_StubComponent)

    def test_chat_model_routes_to_chat(self):
        """A chat-use model is probed through this model's own ``chat()``."""
        calls = []

        def stub_chat(self, provider, messages, model=None, stream=False,
                      tools=None, prepend_messages=None, **kwargs):
            calls.append((model, prepend_messages))
            return {"content": "pong"}

        self._build_stub(chat=stub_chat)
        model = self._model("chat")

        result = model.test_model()

        self.assertEqual(result["state"], "success")
        self.assertEqual(len(calls), 1)
        probed_model, prepend_messages = calls[0]
        self.assertEqual(probed_model, model, "must probe itself, not some other model")
        self.assertEqual(prepend_messages[0]["role"], "user")

    def test_embedding_model_routes_to_embedding(self):
        """An embedding-use model is probed through this model's own ``embedding()``."""
        calls = []

        def stub_embedding(self, provider, texts, model=None):
            calls.append(model)
            return [[0.1, 0.2, 0.3]]

        self._build_stub(embedding=stub_embedding)
        model = self._model("embedding")

        result = model.test_model()

        self.assertEqual(result["state"], "success")
        self.assertIn("3-dimension", result["message"])
        self.assertEqual(calls, [model])

    def test_image_generation_model_routes_to_generate(self):
        """An image_generation-use model is probed through this model's own ``generate()``."""
        calls = []

        def stub_generate(self, provider, input_data, model=None, stream=False, **kwargs):
            calls.append(model)
            return ({"ok": True}, ["http://example.com/a.png"])

        self._build_stub(generate=stub_generate)
        model = self._model("image_generation")

        result = model.test_model()

        self.assertEqual(result["state"], "success")
        self.assertEqual(calls, [model])

    def test_rerank_has_no_generic_probe(self):
        """Usages with no generic handler raise a clear error, not a crash."""
        from odoo.exceptions import UserError

        self._build_stub()
        model = self._model("rerank")

        with self.assertRaises(UserError):
            model.test_model()

    def test_generation_not_implemented_falls_back_to_model_listing(self):
        """No ``generate`` on the adapter: fall back to checking model listing."""
        def stub_models(self, provider, model_id=None):
            yield {"name": "probe-model", "details": {}}

        self._build_stub(models=stub_models)
        model = self._model("image_generation")

        result = model.test_model()

        self.assertEqual(result["state"], "warning")
        self.assertIn("does not", result["message"])


@tagged("post_install", "-at_install")
class TestModelConnectivityStorage(TransactionCase):
    """``_run_connectivity_test`` persists the probe result on the record."""

    def test_failed_probe_is_stored_without_raising(self):
        # A service value with no registered adapter: test_model() raises
        # UserError ("No adapter is registered..."), which
        # _run_connectivity_test must catch and turn into a stored "failed"
        # result, not an exception.
        with selection_value(
            self.env["llm.provider"], "service", "no_adapter_probe", "No Adapter"
        ):
            provider = self.env["llm.provider"].create(
                {"name": "No adapter probe", "service": "no_adapter_probe"},
            )
            model = self.env["llm.model"].create(
                {"name": "probe", "provider_id": provider.id, "model_use": "chat"},
            )

            result = model._run_connectivity_test()

        self.assertEqual(result["state"], "failed")
        self.assertEqual(model.test_state, "failed")
