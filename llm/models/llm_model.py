import json
import logging
import time

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Truncation applied to the raw provider payload stored on the record.
TEST_DETAIL_LIMIT = 2000

# Connectivity test payloads: kept deliberately tiny, the goal is to reach
# the endpoint, not to get a useful answer.
TEST_CHAT_PROMPT = "ping"
TEST_CHAT_MAX_TOKENS = 16
TEST_IMAGE_PROMPT = "a small red circle on a white background"
TEST_EMBED_TEXT = "ping"

# Usage categories available for a model. Downstream modules can extend the
# ``model_use`` selection field using the standard Odoo ``selection_add``
# mechanism, e.g.:
#
#   model_use = fields.Selection(
#       selection_add=[("rerank", "Rerank")],
#       ondelete={"rerank": "cascade"},
#   )
MODEL_USE_SELECTION = [
    ("embedding", "Embedding"),
    ("completion", "Completion"),
    ("chat", "Chat"),
    ("rerank", "Rerank"),
    ("image_generation", "Image Generation"),
    ("image_ocr", "Image OCR"),
]


class LLMModel(models.Model):
    _name = "llm.model"
    _description = "LLM Model"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True)
    provider_id = fields.Many2one("llm.provider", required=True, ondelete="cascade")
    publisher_id = fields.Many2one(
        "llm.publisher",
        string="Publisher",
        ondelete="restrict",
        tracking=True,
        help="The organization or entity that published this model",
    )

    model_use = fields.Selection(
        selection=MODEL_USE_SELECTION,
        required=True,
        default="chat",
    )
    supports_image_input = fields.Boolean(
        string="Image Input",
        default=False,
        help="Whether this chat model accepts images as part of the input "
        "(vision/multimodal understanding).",
    )
    supports_image_output = fields.Boolean(
        string="Image Output",
        default=False,
        help="Whether this model can generate images in chat responses "
        "(e.g., Gemini Image via chat completions protocol).",
    )
    is_default = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    # Model details
    details = fields.Json()
    model_info = fields.Json()
    parameters = fields.Text()
    template = fields.Text()

    # Connectivity test
    test_state = fields.Selection(
        [
            ("untested", "Not Tested"),
            ("success", "Reachable"),
            ("warning", "Partially Reachable"),
            ("failed", "Failed"),
        ],
        string="Test Status",
        default="untested",
        readonly=True,
        copy=False,
        tracking=True,
    )
    test_date = fields.Datetime(string="Last Test", readonly=True, copy=False)
    test_message = fields.Char(string="Test Result", readonly=True, copy=False)
    test_detail = fields.Text(string="Test Details", readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.is_default:
                # Ensure only one default per provider/use combo
                self.search(
                    [
                        ("provider_id", "=", record.provider_id.id),
                        ("model_use", "=", record.model_use),
                        ("is_default", "=", True),
                        ("id", "!=", record.id),
                    ]
                ).write({"is_default": False})
        return records

    def chat(self, messages, stream=False, tools=None, tool_choice="auto", **kwargs):
        """Send chat messages using this model"""
        return self.provider_id.chat(
            messages,
            model=self,
            stream=stream,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

    def embedding(self, texts):
        """Generate embeddings using this model"""
        return self.provider_id.embedding(texts, model=self)

    def generate(self, input_data, stream=False, **kwargs):
        """Generate content using this model

        Args:
            input_data: Input data for generation (could be text, prompt, or structured data)
            stream: Whether to stream the response
            **kwargs: Additional provider-specific parameters

        Returns:
            Generated content from the provider
        """
        return self.provider_id.generate(
            input_data, model=self, stream=stream, **kwargs
        )

    def action_open_fetch_this_model_wizard(self):
        self.ensure_one()
        # Call the provider's action_fetch_models with context for specific model
        return self.provider_id.with_context(
            default_model_to_fetch=self.name
        ).action_fetch_models()

    # ------------------------------------------------------------------
    # Connectivity test
    # ------------------------------------------------------------------

    def action_test_connectivity(self):
        """Test the provider API for the selected models and store the outcome.

        Chat (and multimodal) models get a minimal chat request; image
        generation models get a minimal generation request, falling back to a
        model lookup when the provider has no generation implementation.
        """
        results = [record._run_connectivity_test() for record in self]
        return self._notify_test_results(results)

    def _run_connectivity_test(self):
        """Run the probe for a single model, never raising on API failures."""
        self.ensure_one()

        started = time.monotonic()
        try:
            # Savepoint so a failing probe cannot leave the transaction dirty
            # before we write the test result below.
            with self.env.cr.savepoint():
                result = self.test_model()
        except Exception as error:  # noqa: BLE001 - any error means "unreachable"
            _logger.warning(
                "Connectivity test failed for llm.model %s (%s): %s",
                self.id,
                self.name,
                error,
                exc_info=True,
            )
            result = {
                "state": "failed",
                "message": str(error)
                if isinstance(error, UserError)
                else _(
                    "%(error_type)s: %(error)s",
                    error_type=type(error).__name__,
                    error=error,
                ),
                "detail": "",
            }

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return self._store_test_result(result, elapsed_ms)

    def test_model(self):
        """Probe this model's API and report reachability.

        Routed purely on :attr:`model_use`, never on the provider's service:
        connectivity testing is a property of what kind of model this is
        (chat, embedding, image generation, ...), dispatched to whichever of
        this record's own ``chat``/``embedding``/``generate`` methods
        matches -- the same methods any other caller would use this model
        through.

        A service needing a different probe for one usage overrides the
        matching ``_test_<usage>_model`` method on ``llm.provider`` the plain
        Odoo way (``_inherit`` + ``super()``) -- see
        ``llm_openai.models.openai_provider`` for a real one
        (``_test_image_generation_model``, since the SDK's dedicated image
        endpoint beats a generic ``generate()`` probe).

        Returns:
            dict with keys:
                - state: "success", "warning" or "failed"
                - message: short human readable summary
                - detail: optional longer text (excerpt of the raw response)

        Raises:
            Any provider/API exception. Callers are expected to catch them
            (see :meth:`_run_connectivity_test`).
        """
        self.ensure_one()
        handler = self._get_test_handler_name()
        if not handler:
            raise UserError(
                _(
                    "Connectivity test is not available for models used as '%s'.",
                    self.model_use,
                ),
            )
        return getattr(self, handler)()

    def _can_test_model(self):
        """Return True when a connectivity probe exists for this model.

        EXTENSION POINT: override (together with ``_test_<usage>_model``) when
        a service can probe usages the generic layer does not handle.
        """
        self.ensure_one()
        return bool(self._get_test_handler_name())

    def _get_test_handler_name(self):
        """Map this model's usage to the method probing it.

        Usages backed by a text endpoint route to the chat probe; embeddings
        and image generation have dedicated probes. Usages with no generic
        probe (e.g. ``rerank``, ``image_ocr``) return ``False``: connectivity
        testing is skipped unless a subclass or adapter provides one.

        EXTENSION POINT: override to support additional usages added via
        ``selection_add`` on ``model_use``.
        """
        return {
            "chat": "_test_chat_model",
            "completion": "_test_chat_model",
            "embedding": "_test_embedding_model",
            "image_generation": "_test_generation_model",
        }.get(self.model_use, False)

    def _test_chat_model(self):
        """Send a minimal chat request to check the chat endpoint."""
        self.ensure_one()
        response = self.chat(
            self.env["mail.message"],  # no history, the prompt is prepended
            stream=False,
            prepend_messages=[{"role": "user", "content": TEST_CHAT_PROMPT}],
            max_tokens=TEST_CHAT_MAX_TOKENS,
        )

        if not isinstance(response, dict):
            # Defensive: a provider returning a generator for stream=False
            return {
                "state": "warning",
                "message": _("Chat endpoint answered with an unexpected payload."),
                "detail": str(response),
            }

        if response.get("error"):
            return {
                "state": "failed",
                "message": _("The chat endpoint returned an error."),
                "detail": str(response["error"]),
            }

        content = self.provider_id._extract_content_text(response.get("content") or "")
        if not content and not response.get("tool_calls"):
            return {
                "state": "warning",
                "message": _("Chat endpoint reached but the answer was empty."),
                "detail": self._test_dump(response),
            }

        return {
            "state": "success",
            "message": _("Chat endpoint reached, the model answered."),
            "detail": content or self._test_dump(response),
        }

    def _test_embedding_model(self):
        """Request a minimal embedding to check the embedding endpoint."""
        self.ensure_one()
        response = self.embedding([TEST_EMBED_TEXT])

        vectors = self._test_extract_embeddings(response)
        if not vectors:
            return {
                "state": "warning",
                "message": _("Embedding endpoint reached but no vector was returned."),
                "detail": self._test_dump(response),
            }

        dimensions = len(vectors[0]) if hasattr(vectors[0], "__len__") else 0
        return {
            "state": "success",
            "message": _(
                "Embedding endpoint reached, %(dims)d-dimension vector returned.",
                dims=dimensions,
            ),
            "detail": self._test_dump({"count": len(vectors), "dimensions": dimensions}),
        }

    @staticmethod
    def _test_extract_embeddings(response):
        """Normalize an ``embedding()`` result into a list of vectors."""
        if response is None:
            return []
        if isinstance(response, dict):
            data = response.get("data")
            if isinstance(data, list):
                return [
                    item.get("embedding") if isinstance(item, dict) else item
                    for item in data
                ]
            return response.get("embeddings") or response.get("embedding") or []
        if isinstance(response, (list, tuple)):
            return list(response)
        return []

    def _test_generation_model(self):
        """Run a minimal generation request (image or other binary output).

        When the provider has no ``generate`` implementation, fall back to
        checking that the model can be retrieved from the provider API: that
        still validates credentials, base URL and model name, so the result is
        reported as a partial success.
        """
        self.ensure_one()
        try:
            result = self.generate(TEST_IMAGE_PROMPT, stream=False)
        except NotImplementedError:
            return self._test_generation_fallback()

        output, urls = self._test_split_generate_result(result)

        if isinstance(output, dict) and output.get("error"):
            return {
                "state": "failed",
                "message": _("The generation endpoint returned an error."),
                "detail": str(output["error"]),
            }

        if not output and not urls:
            return {
                "state": "warning",
                "message": _("Generation endpoint reached but nothing was returned."),
                "detail": self._test_dump(result),
            }

        return {
            "state": "success",
            "message": _(
                "Generation endpoint reached, %(count)d result(s) returned.",
                count=len(urls) if urls else 1,
            ),
            "detail": self._test_dump({"output": output, "urls": urls}),
        }

    def _test_generation_fallback(self):
        """Reachability check used when generation is not implemented."""
        self.ensure_one()
        try:
            available = self._test_model_is_listed()
        except NotImplementedError:
            return {
                "state": "failed",
                "message": _(
                    "Service '%s' implements neither generation nor model listing, "
                    "connectivity cannot be checked.",
                    self.provider_id.service,
                ),
                "detail": "",
            }

        if not available:
            return {
                "state": "failed",
                "message": _(
                    "API reached but model '%s' was not returned by the provider.",
                    self.name,
                ),
                "detail": "",
            }

        return {
            "state": "warning",
            "message": _(
                "API credentials valid and model '%s' exists, but service '%s' does not "
                "implement generation, so no image was requested.",
                self.name,
                self.provider_id.service,
            ),
            "detail": "",
        }

    def _test_model_is_listed(self):
        """Return True when the provider API knows about this model."""
        self.ensure_one()
        for model_data in self.provider_id.list_models(model_id=self.name):
            details = model_data.get("details") or {}
            if (model_data.get("name") or details.get("id")) == self.name:
                return True
        return False

    @staticmethod
    def _test_split_generate_result(result):
        """Normalize ``generate()`` output into an ``(output, urls)`` tuple."""
        if isinstance(result, tuple) and len(result) == 2:
            output, urls = result
            return output, list(urls or [])
        return result, []

    @staticmethod
    def _test_dump(value):
        """Serialize a probe payload for storage in the test details field."""
        try:
            return json.dumps(value, default=str, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(value)

    def _store_test_result(self, result, elapsed_ms):
        """Persist a probe result on the record and log it in the chatter."""
        self.ensure_one()
        provider = self.provider_id
        state = result.get("state") or "failed"
        message = provider._sanitize_test_output(result.get("message") or "")
        detail = provider._sanitize_test_output(result.get("detail") or "")

        self.write(
            {
                "test_state": state,
                "test_date": fields.Datetime.now(),
                "test_message": _(
                    "%(message)s (%(elapsed)d ms)",
                    message=message,
                    elapsed=elapsed_ms,
                ),
                "test_detail": detail[:TEST_DETAIL_LIMIT],
            },
        )

        self._message_log(
            body=Markup("<p><b>%s</b><br/>%s</p>")
            % (self._test_state_label(state), self.test_message),
        )

        return {"model": self, "state": state, "message": self.test_message}

    @api.model
    def _test_state_label(self, state):
        labels = dict(self.fields_get(["test_state"])["test_state"]["selection"])
        return labels.get(state, state)

    @api.model
    def _notify_test_results(self, results):
        """Build the client notification summarizing one or several probes."""
        if not results:
            return False

        states = [result["state"] for result in results]
        worst = (
            "failed"
            if "failed" in states
            else "warning"
            if "warning" in states
            else "success"
        )
        notification_type = {
            "success": "success",
            "warning": "warning",
            "failed": "danger",
        }[worst]

        if len(results) == 1:
            title = self._test_state_label(results[0]["state"])
            message = "%s: %s" % (results[0]["model"].name, results[0]["message"])
        else:
            title = _("Connectivity Test")
            message = "\n".join(
                "%s - %s: %s"
                % (
                    self._test_state_label(result["state"]),
                    result["model"].name,
                    result["message"],
                )
                for result in results
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": notification_type,
                "sticky": worst != "success",
            },
        }
