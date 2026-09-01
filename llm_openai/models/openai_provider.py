from openai import BadRequestError, UnprocessableEntityError

from odoo import _, fields, models

from odoo.addons.llm.models.llm_model import TEST_IMAGE_PROMPT
from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service

# A 4xx raised by the model itself proves the endpoint was reached and the
# credentials were accepted: only the request payload was refused.
TEST_REACHED_ERRORS = (BadRequestError, UnprocessableEntityError)


class LLMProvider(models.Model):
    _inherit = "llm.provider"

    # The service itself is implemented by the ``openai.provider.adapter``
    # component (``llm_openai/components/``), resolved through
    # ``llm.provider._get_adapter()``. Only the selection entry belongs here.
    service = fields.Selection(
        selection_add=[("openai", "OpenAI")],
        ondelete={"openai": archive_dangling_service},
    )


class LLMModel(models.Model):
    _inherit = "llm.model"

    # ------------------------------------------------------------------
    # Connectivity test
    # ------------------------------------------------------------------
    #
    # Overrides the base ``_test_generation_model`` the plain Odoo way, not
    # through the ``llm.provider.adapter`` component: connectivity testing is
    # routed on ``self.model_use`` by ``llm.model.test_model``, never on the
    # adapter (see ``llm/models/llm_model.py``).
    #
    # A plain ``_inherit`` override runs for *every* model record regardless
    # of its provider's service -- unlike component dispatch, which is scoped
    # by ``_usage`` -- so it must guard on ``self.provider_id.service`` and
    # fall back to ``super()`` for every other service.

    def _test_generation_model(self):
        """Ask for one small image to check the generation endpoint.

        The dedicated ``images.generate`` endpoint is a better probe than the
        generic ``generate()`` fallback other services get, since OpenAI's
        image models are not reachable through ``chat.completions``.
        """
        self.ensure_one()
        if self.provider_id.service != "openai":
            return super()._test_generation_model()

        try:
            response = self.provider_id.client.images.generate(
                model=self.name,
                prompt=TEST_IMAGE_PROMPT,
                n=1,
            )
        except TEST_REACHED_ERRORS as error:
            return {
                "state": "warning",
                "message": _(
                    "Image endpoint reached and credentials accepted, but the "
                    "model rejected the test request.",
                ),
                "detail": str(error),
            }

        images = getattr(response, "data", None) or []
        if not images:
            return {
                "state": "warning",
                "message": _("Image endpoint reached but no image was returned."),
                "detail": self._test_dump(self._test_response_dump(response)),
            }

        return {
            "state": "success",
            "message": _(
                "Image endpoint reached, %(count)d image(s) generated.",
                count=len(images),
            ),
            "detail": self._test_dump(
                [self._test_image_summary(image) for image in images],
            ),
        }

    @staticmethod
    def _test_image_summary(image):
        """Summarize one generated image without storing its base64 payload."""
        summary = {}
        if getattr(image, "url", None):
            summary["url"] = image.url
        if getattr(image, "b64_json", None):
            summary["b64_json_length"] = len(image.b64_json)
        if getattr(image, "revised_prompt", None):
            summary["revised_prompt"] = image.revised_prompt
        return summary or {"image": "returned without url or payload"}

    @staticmethod
    def _test_response_dump(response):
        """Best-effort serializable view of an API response object."""
        try:
            return response.model_dump()
        except AttributeError:
            return str(response)
