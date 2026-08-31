import logging
import time

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Truncation applied to the raw provider payload stored on the record.
TEST_DETAIL_LIMIT = 2000

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

    def chat(self, messages, stream=False, **kwargs):
        """Send chat messages using this model"""
        return self.provider_id.chat(messages, model=self, stream=stream, **kwargs)

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
                result = self.provider_id.test_model(self)
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
