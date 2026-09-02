import json
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LLMProvider(models.Model):
    _name = "llm.provider"
    # ``collection.base`` makes this model a component collection, so service
    # adapters can be registered against it (see llm/components/);
    # ``llm.service.dispatch.mixin`` resolves them.
    _inherit = ["mail.thread", "collection.base", "llm.service.dispatch.mixin"]
    _description = "LLM Provider"

    name = fields.Char(required=True)
    service = fields.Selection(
        # Empty here on purpose: the base addon ships no provider. Each provider
        # addon adds its key with ``selection_add`` plus an ``ondelete`` policy
        # (see llm_openai). A static list is what makes the value validated on
        # write and the label translatable -- a ``selection=lambda`` leaves
        # ``Selection._selection`` as None, which disables validation entirely.
        selection=[],
        required=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    api_key = fields.Char()
    api_base = fields.Char()
    model_ids = fields.One2many("llm.model", "provider_id", string="Models")

    @api.constrains("name")
    def _check_unique_name(self):
        other_providers = self.search([("id", "not in", self.ids)])
        existing_names_lower = [p.name.lower() for p in other_providers if p.name]
        for record in self:
            if record.name and record.name.lower() in existing_names_lower:
                raise ValidationError(
                    _("The provider name must be unique (case-insensitive)."),
                )

        return True

    @property
    def client(self):
        """Get client instance using dispatch pattern"""
        return self._dispatch("get_client")

    # ------------------------------------------------------------------
    # Service dispatch
    # ------------------------------------------------------------------
    #
    # Resolution lives in ``llm.service.dispatch.mixin``; adapters are the
    # ``llm.provider.adapter`` components (see llm/components/), one per
    # service, resolved by ``_usage`` == ``service``.
    #
    # ``test_model`` and ``determine_model_use`` are not dispatched: neither
    # has a service-specific variant any more (connectivity testing is routed
    # on ``model.model_use``, not on the adapter -- see :meth:`test_model`;
    # nothing ever implemented ``determine_model_use``). Both are plain model
    # methods, overridden the usual Odoo way (``_inherit`` + ``super()``)
    # rather than through dispatch.

    def chat(
        self,
        messages,
        model=None,
        stream=False,
        tools=None,
        prepend_messages=None,
        **kwargs,
    ):
        """Send chat messages using this provider.

        Args:
            messages: mail.message recordset (Odoo records) to send
            model: Optional specific model to use
            stream: Whether to stream the response
            tools: llm.tool recordset of available tools
            prepend_messages: List of pre-formatted message dicts to prepend (e.g., system prompts)
            **kwargs: Additional provider-specific parameters

        Returns:
            Generator yielding response chunks if streaming, else complete response
        """
        # Hook: allow extensions to modify prepend_messages (e.g., add tool consent)
        prepend_messages = self._prepare_prepend_messages(prepend_messages, tools)

        # Normalize prepend_messages for the specific provider format
        prepend_messages = self._dispatch(
            "normalize_prepend_messages",
            prepend_messages,
        )

        return self._dispatch(
            "chat",
            messages,
            model=model,
            stream=stream,
            tools=tools,
            prepend_messages=prepend_messages,
            **kwargs,
        )

    def _prepare_prepend_messages(self, prepend_messages, tools):
        """Hook for extensions to modify prepend messages before sending to provider.

        Injects tool consent instructions for tools that require user consent
        before execution, in addition to any base behaviour.

        Args:
            prepend_messages: List of pre-formatted message dicts (e.g., system prompts)
            tools: llm.tool recordset of available tools

        Returns:
            List of message dicts to prepend to the conversation
        """
        prepend_messages = prepend_messages or []

        if not tools:
            return prepend_messages

        consent_required = tools.filtered(lambda t: t.requires_user_consent)
        if not consent_required:
            return prepend_messages

        return self._inject_tool_consent(prepend_messages, consent_required)

    @api.model
    def _is_tool_call_complete(self, function_data, expected_endings=("]", "}")):
        """Check if a tool call is complete (utility function for providers).

        Args:
            function_data: Dictionary with 'name' and 'arguments' keys
            expected_endings: Tuple of valid JSON ending characters

        Returns:
            bool: True if the tool call appears complete
        """
        tool_name = function_data.get("name")
        args_str = function_data.get("arguments", "").strip()

        if not tool_name or not args_str:
            return False

        try:
            json.loads(args_str)
            if args_str.endswith(expected_endings):
                return True
        except json.JSONDecodeError:
            pass

        return False

    def _inject_tool_consent(self, prepend_messages, consent_tools):
        """Add consent instructions to prepend messages.

        Args:
            prepend_messages: List of message dicts to modify
            consent_tools: llm.tool recordset of tools requiring consent

        Returns:
            List of message dicts with consent instructions added
        """
        tool_names = ", ".join([f"'{t.name}'" for t in consent_tools])
        config = self.env["llm.tool.consent.config"].get_active_config()
        consent_instruction = config.system_message_template.format(
            tool_names=tool_names
        )

        # Make a copy to avoid modifying the original
        prepend_messages = list(prepend_messages or [])

        # Find existing system message and append consent instructions
        for msg in prepend_messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")

                # Handle list format - modify in place (preserves format)
                if (
                    isinstance(content, list)
                    and content
                    and isinstance(content[0], dict)
                ):
                    existing_text = self._extract_content_text(content)
                    separator = "\n\n" if existing_text else ""
                    content[0]["text"] = (
                        f"{existing_text}{separator}{consent_instruction}"
                    )
                else:
                    # String format
                    existing_text = self._extract_content_text(content)
                    separator = "\n\n" if existing_text else ""
                    msg["content"] = f"{existing_text}{separator}{consent_instruction}"

                return prepend_messages

        # No system message found, insert one at the beginning
        prepend_messages.insert(
            0,
            {
                "role": "system",
                "content": consent_instruction,
            },
        )

        return prepend_messages

    def _extract_content_text(self, content):
        """Extract plain text from message content.

        Handles both string and OpenAI list formats:
        - String: "hello" → "hello"
        - List: [{"type": "text", "text": "hello"}] → "hello"

        Args:
            content: Message content (string or list format)

        Returns:
            str: Plain text content
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
        return ""

    def embedding(self, texts, model=None):
        """Generate embeddings using this provider"""
        return self._dispatch("embedding", texts, model=model)

    def generate(self, input_data, model=None, stream=False, **kwargs):
        """Generate content using this provider

        Args:
            input_data: Input data for generation (could be text, prompt, or structured data)
            model: Optional specific model to use
            stream: Whether to stream the response
            **kwargs: Additional provider-specific parameters

        Returns:
            tuple: (output_dict, urls_list) where:
                - output_dict: Dictionary containing provider-specific output data
                - urls_list: List of dictionaries with URL metadata
        """
        return self._dispatch(
            "generate",
            input_data,
            model=model,
            stream=stream,
            **kwargs,
        )

    def list_models(self, model_id=None):
        """List available models from the provider"""
        return self._dispatch("models", model_id=model_id)

    # ------------------------------------------------------------------
    # Connectivity test support
    # ------------------------------------------------------------------
    #
    # The probe itself (test_model and friends) lives on ``llm.model``: testing
    # a model's reachability is that model's concern, dispatched to whichever
    # of this provider's own chat/embedding/generate methods matches its
    # model_use. Only what genuinely belongs to the provider -- keeping its
    # credentials out of stored/displayed text -- stays here.

    def _sanitize_test_output(self, text):
        """Strip the API key from any text before it is stored or displayed."""
        text = text or ""
        if self.api_key and self.api_key in text:
            text = text.replace(self.api_key, "***")
        return text

    def action_fetch_models(self):
        """Fetch models from provider and open import wizard"""
        self.ensure_one()

        # Create wizard first so it has an ID
        wizard = self.env["llm.fetch.models.wizard"].create(
            {
                "provider_id": self.id,
            },
        )

        # Get existing models for comparison
        existing_models = {
            model.name: model
            for model in self.env["llm.model"].search([("provider_id", "=", self.id)])
        }

        # Fetch models from provider
        model_to_fetch = self.env.context.get("default_model_to_fetch")
        if model_to_fetch:
            models_data = self.list_models(model_id=model_to_fetch)
        else:
            models_data = self.list_models()

        # Track models to prevent duplicates
        wizard_models = set()
        lines_to_create = []

        for model_data in models_data:
            details = model_data.get("details", {})
            name = model_data.get("name") or details.get("id")

            if not name:
                continue

            # Skip duplicates
            if name in wizard_models:
                continue
            wizard_models.add(name)

            # Determine model use and capabilities
            capabilities = details.get("capabilities", ["chat"])
            model_use = self._determine_model_use(name, capabilities)
            supports_image_input = any(
                cap in capabilities for cap in ("multimodal", "vision")
            )

            # Check against existing models
            existing = existing_models.get(name)
            status = "new"
            if existing:
                status = "modified" if existing.details != details else "existing"

            lines_to_create.append(
                {
                    "wizard_id": wizard.id,
                    "name": name,
                    "model_use": model_use,
                    "supports_image_input": supports_image_input,
                    "status": status,
                    "details": details,
                    "existing_model_id": existing.id if existing else False,
                    "selected": status in ["new", "modified"],
                },
            )

        # Create all lines
        if lines_to_create:
            self.env["llm.fetch.models.line"].create(lines_to_create)

        # Return action to open the wizard
        return {
            "type": "ir.actions.act_window",
            "res_model": "llm.fetch.models.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "name": _("Import Models"),
        }

    def _determine_model_use(self, name, capabilities):
        """
        Determine the primary model use based on capabilities.

        This method classifies models into Odoo's model_use categories based on their
        capabilities. The classification follows a priority order from most specialized
        to most general.

        EXTENSION POINT: Override this method in your provider class to add custom
        model types or modify classification logic.

        Args:
            name (str): Model name/ID from the provider
            capabilities (list): List of capability strings (usually from API response)

        Returns:
            str: One of the model_use values defined on ``llm.model``
                 ("embedding", "rerank", "image_generation", "image_ocr",
                 "completion", "chat")

        Priority Order:
            1. embedding - Specialized embedding models
            2. rerank - Specialized reranking models
            3. image_generation - Models that generate images
            4. image_ocr - Models specialized in reading text from images
            5. chat - General conversational models (default)

        Standard Capability Names:
            - "chat": Text-based conversations
            - "embedding"/"text-embedding": Vector embeddings
            - "rerank": Document/passage reranking
            - "image_generation": Image generation
            - "ocr"/"image_ocr": Text extraction from images
            - "completion": Text completion
            - "function_calling": Tool/function support

        Example Override:
            ```python
            class MyProvider(models.Model):
                _inherit = "llm.provider"

                def _determine_model_use(self, name, capabilities):
                    # Add custom model type
                    if "audio" in capabilities:
                        return "audio"
                    # Fall back to parent logic for standard types
                    return super()._determine_model_use(name, capabilities)
            ```

        See Also:
            - llm_mistral.models.mistral_provider for a working example
            - _<provider>_parse_model() for setting capabilities
        """
        # Priority 1: Embedding models (specialized, distinct use case)
        if (
            any(cap in capabilities for cap in ["embedding", "text-embedding"])
            or "embedding" in name.lower()
        ):
            return "embedding"

        # Priority 2: Rerank models (specialized, distinct use case)
        if any(cap in capabilities for cap in ["rerank"]) or "rerank" in name.lower():
            return "rerank"

        # Priority 3: Image generation models
        if any(cap in capabilities for cap in ["image_generation"]):
            return "image_generation"

        # Priority 4: Image OCR models
        if any(cap in capabilities for cap in ["ocr", "image_ocr"]):
            return "image_ocr"

        # Priority 5: Chat models (default for most LLMs)
        return "chat"

    def get_model(self, model=None, model_use="chat"):
        """Get a model to use for the given purpose

        Args:
            model: Optional specific model to use
            model_use: Type of model to get if no specific model provided

        Returns:
            llm.model record to use
        """
        if model:
            return model

        # Get models from provider
        models = self.model_ids

        # Filter for default model of requested type
        default_models = models.filtered(
            lambda m: m.is_default and m.model_use == model_use,
        )

        if not default_models:
            # Fallback to any model of requested type
            default_models = models.filtered(lambda m: m.model_use == model_use)

        if not default_models:
            raise ValueError(f"No {model_use} model found for provider {self.name}")

        return default_models[0]

    @staticmethod
    def serialize_datetime(obj):
        """Helper function to serialize datetime objects to ISO format strings."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    @staticmethod
    def serialize_model_data(data: dict) -> dict:
        """
        Recursively process dictionary to serialize datetime objects
        and handle any other non-serializable types.

        Args:
            data (dict): Dictionary potentially containing datetime objects

        Returns:
            dict: Processed dictionary with datetime objects converted to ISO strings
        """
        return {
            key: LLMProvider.serialize_datetime(value)
            if isinstance(value, datetime)
            else LLMProvider.serialize_model_data(value)
            if isinstance(value, dict)
            else [
                LLMProvider.serialize_model_data(item)
                if isinstance(item, dict)
                else LLMProvider.serialize_datetime(item)
                for item in value
            ]
            if isinstance(value, list)
            else value
            for key, value in data.items()
        }

    def format_tools(self, tools):
        """Format tools for the specific provider"""
        return self._dispatch("format_tools", tools)

    def format_messages(self, messages, system_prompt=None, model=None):
        """Format messages for this provider

        Args:
            messages: List of messages to format for specific provider, could be mail.message record set or similar data format
            system_prompt: Optional system prompt to include at the beginning of the messages
            model: llm.model record (to determine if it supports image input)

        Returns:
            List of formatted messages in provider-specific format
        """
        return self._dispatch(
            "format_messages",
            messages,
            system_prompt=system_prompt,
            model=model,
        )

    def _get_provider_tool_params(self, tools, kwargs):
        """Hook for provider-specific tool parameters."""
        return {}
