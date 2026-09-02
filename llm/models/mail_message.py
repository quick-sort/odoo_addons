import base64
import json
import logging

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

IMAGE_MIMETYPES = (
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
)

# Magic bytes for image type detection
IMAGE_MAGIC_BYTES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",  # RIFF....WEBP
}

PDF_MIMETYPES = ("application/pdf",)

# Audio mimetypes - only supported by OpenAI gpt-4o-audio-preview models
AUDIO_MIMETYPES = (
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
    "audio/flac",
    "audio/webm",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
)

# Video mimetypes - NOT supported by any LLM provider
VIDEO_MIMETYPES = (
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/ogg",
)

# Office document mimetypes - NOT supported via chat API
OFFICE_MIMETYPES = (
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
)

TEXT_MIMETYPES = (
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "text/css",
    "text/javascript",
    "text/xml",
    "text/x-python",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-python-code",
)

SUPPORTED_IMAGE_MIMETYPES = IMAGE_MIMETYPES


def _detect_image_mimetype(raw_bytes):
    """Detect the real image mimetype from magic bytes.

    Args:
        raw_bytes: The raw image bytes

    Returns:
        The detected mimetype or None if not recognized
    """
    for magic, mimetype in IMAGE_MAGIC_BYTES.items():
        if raw_bytes.startswith(magic):
            # Special check for WebP: must have WEBP after RIFF header
            if magic == b"RIFF" and len(raw_bytes) >= 12:
                if raw_bytes[8:12] != b"WEBP":
                    continue
            return mimetype
    return None


def _detect_audio_format(raw_bytes):
    """Detect audio format from magic bytes for OpenAI API.

    Args:
        raw_bytes: The raw audio bytes

    Returns:
        The format string for OpenAI API (wav, mp3, flac, ogg) or None
    """
    # WAV: RIFF....WAVE
    if raw_bytes[:4] == b"RIFF" and len(raw_bytes) >= 12:
        if raw_bytes[8:12] == b"WAVE":
            return "wav"
    # MP3: ID3 tag or sync bytes
    if raw_bytes[:3] == b"ID3" or raw_bytes[:2] == b"\xff\xfb":
        return "mp3"
    # FLAC
    if raw_bytes[:4] == b"fLaC":
        return "flac"
    # OGG
    if raw_bytes[:4] == b"OggS":
        return "ogg"
    # M4A/MP4 audio
    if raw_bytes[4:8] == b"ftyp":
        return "mp4"
    return None


class MailMessage(models.Model):
    _inherit = "mail.message"

    LLM_XMLIDS = (
        "llm.mt_tool",
        "llm.mt_user",
        "llm.mt_assistant",
        "llm.mt_system",
    )

    llm_role = fields.Char(
        string="LLM Role",
        compute="_compute_llm_role",
        store=True,
        index=True,  # Add index for better query performance
        help="The LLM role for this message (user, assistant, tool, system)",
    )

    is_error = fields.Boolean(
        string="Is Error Message",
        default=False,
        index=True,
        help="Error messages are shown to users but excluded from LLM context",
    )

    body_json = fields.Json(
        string="JSON Body",
        help="JSON data for tool messages and other structured content",
    )

    user_vote = fields.Integer(
        string="User Vote",
        default=0,
        help="Vote status given by the user. 0: No vote, 1: Upvoted, -1: Downvoted.",
    )

    @api.depends("subtype_id")
    def _compute_llm_role(self):
        """Compute the LLM role for messages based on their subtype."""
        id_to_role, _ = self.get_llm_roles()

        for message in self:
            if message.subtype_id and message.subtype_id.id in id_to_role:
                message.llm_role = id_to_role[message.subtype_id.id]
            else:
                message.llm_role = False

    @tools.ormcache()
    def get_llm_roles(self):
        """Get cached mapping of LLM subtype IDs to clean role names and vice versa.

        Returns:
            tuple: (id_to_role_dict, role_to_id_dict) where:
                - id_to_role_dict: {subtype_id: 'user', subtype_id: 'assistant', ...}
                - role_to_id_dict: {'user': subtype_id, 'assistant': subtype_id, ...}
        """
        id_to_role = {}
        role_to_id = {}

        for xmlid in self.LLM_XMLIDS:
            subtype_id = self.env["ir.model.data"]._xmlid_to_res_id(
                xmlid,
                raise_if_not_found=False,
            )
            if subtype_id:
                # Extract clean role name (e.g., 'user' from 'llm.mt_user')
                role = xmlid.split(".")[-1][3:]  # Remove 'mt_' prefix
                id_to_role[subtype_id] = role
                role_to_id[role] = subtype_id

        return id_to_role, role_to_id

    def get_llm_role(self):
        """Get the LLM role for this message (ensure_one).

        DEPRECATED: Use the llm_role computed field instead.

        Returns:
            str or False: The role name ('user', 'assistant', 'tool', 'system') or False if not an LLM message
        """
        self.ensure_one()
        return self.llm_role

    def is_llm_message(self):
        """Check if messages are LLM messages using the stored field."""
        return {message: bool(message.llm_role) for message in self}

    def is_llm_user_message(self):
        """Check if messages are LLM user messages using the stored field."""
        return {message: message.llm_role == "user" for message in self}

    def is_llm_assistant_message(self):
        """Check if messages are LLM assistant messages using the stored field."""
        return {message: message.llm_role == "assistant" for message in self}

    def is_llm_tool_message(self):
        """Check if messages are LLM tool messages using the stored field."""
        return {message: message.llm_role == "tool" for message in self}

    def is_llm_system_message(self):
        """Check if messages are LLM system messages using the stored field."""
        return {message: message.llm_role == "system" for message in self}

    def _check_llm_role(self, role):
        """Check if messages match a specific LLM role using the stored field.

        Args:
            role (str): The role name ('user', 'assistant', 'tool', 'system')
        """
        return {message: message.llm_role == role for message in self}

    def to_store_format(self):
        """Convert message to store format compatible with Odoo 18.0. Used by frontend js components"""
        self.ensure_one()
        from odoo.addons.mail.tools.discuss import Store

        store = Store()
        store.add(self)
        result = store.get_result()

        return result["mail.message"][0]

    @api.model
    def _message_fetch(self, domain, **kwargs):
        """Override to filter only LLM messages for llm.thread model.

        For LLM threads, we only want to display messages that have an llm_role
        (user, assistant, tool), not system notifications or other message types
        that would clutter the AI conversation interface.
        """
        thread = kwargs.get("thread")
        if thread and thread._name == "llm.thread":
            domain = fields.Domain(domain or []) & fields.Domain(
                [("llm_role", "!=", False)]
            )

        return super()._message_fetch(domain, **kwargs)

    def _extras_to_store(self, store, format_reply):
        """Add LLM-specific fields to the message store."""
        super()._extras_to_store(store, format_reply)

        for message in self:
            data = {}

            # Add LLM-specific fields
            if hasattr(message, "llm_role") and message.llm_role:
                data["llm_role"] = message.llm_role
                # Set is_note=True for LLM messages to get the right bubble style
                data["is_note"] = True

            if hasattr(message, "user_vote"):
                data["user_vote"] = message.user_vote

            if hasattr(message, "body_json") and message.body_json:
                data["body_json"] = message.body_json

            if data:  # Only add to store if we have data
                store.add(message, data)

    def set_user_vote(self, vote_value):
        """Sets the user vote on this message, performing validation checks."""
        self.ensure_one()
        if self.llm_role not in ("assistant", "tool"):
            raise UserError(
                _(
                    "Voting is only allowed on messages generated by the assistant or a tool."
                )
            )
        if not isinstance(vote_value, int) or vote_value not in [-1, 0, 1]:
            raise ValidationError(
                _(
                    "Invalid vote value. Must be an integer: 1 (up), -1 (down), or 0 (none)."
                )
            )
        self.sudo().write({"user_vote": vote_value})

    def _get_attachments_by_mimetype(self, mimetypes):
        """Get attachments filtered by mimetype.

        Base method for DRY attachment extraction. Returns raw attachment records
        filtered by the given mimetypes and having data.

        Args:
            mimetypes: Tuple of mimetype strings to filter by

        Returns:
            Filtered ir.attachment recordset
        """
        self.ensure_one()
        return self.attachment_ids.filtered(
            lambda att: att.mimetype and att.mimetype in mimetypes and att.datas,
        )

    def _get_image_attachments(self):
        """Get image attachments with validated mimetype from magic bytes.

        Returns list of dicts with mimetype (validated), data (base64), and name.
        The mimetype is detected from the actual image content, not from Odoo's
        stored mimetype, to ensure compatibility with strict API validators
        like Anthropic Claude.
        """
        images = []
        for att in self._get_attachments_by_mimetype(SUPPORTED_IMAGE_MIMETYPES):
            try:
                raw_bytes = base64.b64decode(att.datas)
                real_mimetype = _detect_image_mimetype(raw_bytes)

                if real_mimetype:
                    if real_mimetype != att.mimetype:
                        _logger.debug(
                            "Image %s: correcting mimetype from %s to %s",
                            att.name,
                            att.mimetype,
                            real_mimetype,
                        )
                    images.append(
                        {
                            "mimetype": real_mimetype,
                            "data": att.datas.decode("utf-8"),
                            "name": att.name or "image",
                        },
                    )
                else:
                    _logger.warning(
                        "Could not detect image type for %s, using stored mimetype %s",
                        att.name,
                        att.mimetype,
                    )
                    images.append(
                        {
                            "mimetype": att.mimetype,
                            "data": att.datas.decode("utf-8"),
                            "name": att.name or "image",
                        },
                    )
            except (ValueError, TypeError) as e:
                _logger.warning(
                    "Failed to process image attachment %s: %s",
                    att.name,
                    e,
                )
        return images

    def _get_pdf_attachments(self):
        """Get PDF attachments as base64 data."""
        return [
            {
                "mimetype": att.mimetype,
                "data": att.datas.decode("utf-8"),
                "name": att.name or "document.pdf",
            }
            for att in self._get_attachments_by_mimetype(PDF_MIMETYPES)
        ]

    def _get_text_attachments(self):
        """Get text attachments with decoded content."""
        texts = []
        for att in self._get_attachments_by_mimetype(TEXT_MIMETYPES):
            try:
                raw_data = base64.b64decode(att.datas)
                content = raw_data.decode("utf-8")
                texts.append(
                    {
                        "mimetype": att.mimetype,
                        "content": content,
                        "name": att.name or "file.txt",
                    },
                )
            except (UnicodeDecodeError, ValueError) as e:
                _logger.warning("Failed to decode text attachment %s: %s", att.name, e)
        return texts

    def _get_audio_attachments(self):
        """Get audio attachments with detected format for OpenAI API.

        Returns list of dicts with format (wav, mp3, etc.), data (base64), and name.
        Only for use with OpenAI gpt-4o-audio-preview models.
        """
        audios = []
        for att in self._get_attachments_by_mimetype(AUDIO_MIMETYPES):
            try:
                raw_bytes = base64.b64decode(att.datas)
                audio_format = _detect_audio_format(raw_bytes)
                if audio_format:
                    audios.append(
                        {
                            "format": audio_format,
                            "data": att.datas.decode("utf-8"),
                            "name": att.name or "audio",
                        },
                    )
                else:
                    _logger.warning("Could not detect audio format for %s", att.name)
            except (ValueError, TypeError) as e:
                _logger.warning(
                    "Failed to process audio attachment %s: %s",
                    att.name,
                    e,
                )
        return audios

    def _get_unsupported_attachments(
        self,
        provider_service,
        is_multimodal=False,
    ):
        """Get list of attachments not supported by the current provider/model.

        This method supports both single messages and recordsets, which is essential
        for validating the ENTIRE conversation context before sending to the LLM.

        Why check the full context?
        ---------------------------
        When a user switches LLM models mid-conversation, previously valid attachments
        may become incompatible. For example:
        - User sends image to multimodal model → works
        - User switches to text-only model → images in context unsupported

        Supported file types:
        - Images (JPEG, PNG, GIF, WebP) - requires multimodal model
        - PDFs - requires multimodal model
        - Text files (plain text, markdown, code) - always supported

        Unsupported (user is notified, file skipped):
        - Audio files - not yet implemented
        - Video files - not supported by any LLM
        - Office documents (Word, Excel, PPT) - must convert to PDF first

        The notification message has is_error=True so it's excluded from
        future LLM context, allowing the conversation to continue normally.

        Args:
            provider_service: The provider service name (e.g., 'anthropic', 'openai')
            is_multimodal: Whether the model supports images/PDFs

        Returns:
            List of dicts with name, mimetype, and reason for each unsupported attachment
        """
        unsupported = []

        for message in self:
            for att in message.attachment_ids:
                if not att.mimetype or not att.datas:
                    continue

                mimetype = att.mimetype
                reason = None

                # Video - never supported by any LLM
                if mimetype in VIDEO_MIMETYPES:
                    reason = _("Video files are not supported")

                # Office documents - must convert to PDF
                elif mimetype in OFFICE_MIMETYPES:
                    reason = _("Office documents must be converted to PDF first")

                # Audio - not yet implemented
                elif mimetype in AUDIO_MIMETYPES:
                    reason = _("Audio files are not yet supported")

                # Images/PDFs - only with multimodal models
                elif mimetype in IMAGE_MIMETYPES and not is_multimodal:
                    reason = _("This model does not support images")

                elif mimetype in PDF_MIMETYPES and not is_multimodal:
                    reason = _("This model does not support PDFs")

                if reason:
                    unsupported.append(
                        {
                            "name": att.name,
                            "mimetype": mimetype,
                            "reason": reason,
                        },
                    )

        return unsupported

    # ------------------------------------------------------------------
    # Tool call handling (formerly in llm_tool addon)
    # ------------------------------------------------------------------

    def get_tool_calls(self):
        """Get tool calls from assistant message body_json."""
        self.ensure_one()
        if self.llm_role != "assistant" or not self.body_json:
            return []
        return self.body_json.get("tool_calls", [])

    def has_tool_calls(self):
        """Check if assistant message has tool calls."""
        self.ensure_one()
        return bool(self.get_tool_calls())

    def post_tool_call(self, tool_call, thread_model=None):
        """Create a tool message from tool call data.

        Args:
            tool_call (dict): Tool call data from LLM response
            thread_model (recordset): The thread model that owns this message

        Returns:
            mail.message: The created tool message
        """
        if not self._validate_tool_call(tool_call):
            raise UserError(f"Invalid tool call: {tool_call}")

        function = tool_call.get("function", {})
        tool_name = function.get("name", "unknown_tool")

        # Validate tool exists in thread if thread model is provided
        if thread_model and hasattr(thread_model, "tool_ids"):
            if not thread_model.tool_ids.filtered(lambda t: t.name == tool_name):
                raise UserError(f"Tool '{tool_name}' not found in thread")

        # Validate and parse arguments
        arguments = self._parse_tool_arguments(function.get("arguments", "{}"))

        tool_data = {
            "type": "tool_execution",
            "tool_call_id": tool_call["id"],
            "tool_call": tool_call,
            "status": "requested",
            "tool_name": tool_name,
            "arguments": arguments,
        }

        _logger.debug(f"Creating tool message for {tool_name} with args: {arguments}")

        # Create the message on the thread model if provided, otherwise on self
        if thread_model:
            return thread_model.message_post(
                body=f"Executing {tool_name}",
                body_json=tool_data,
                llm_role="tool",
                author_id=False,
            )
        else:
            # If called on a message record, use its model and res_id
            return self.env["mail.message"].create(
                {
                    "model": self.model,
                    "res_id": self.res_id,
                    "body_json": tool_data,
                    "subtype_xmlid": "llm.mt_tool",
                    "author_id": False,
                    "body": f"Executing {tool_name}",
                }
            )

    def execute_tool_call(self, thread_model=None):
        """Execute a tool call for this message and update it with the result.

        Args:
            thread_model (recordset): The thread model that owns this message

        Yields:
            dict: Status updates for streaming

        Returns:
            mail.message: The updated tool message
        """
        self.ensure_one()

        if self.llm_role != "tool":
            raise UserError("Can only execute tool calls on tool messages")

        tool_data = self.get_tool_data()
        if not tool_data:
            _logger.error(f"No tool data found in message {self.id}")
            raise UserError("Invalid tool message format")

        if tool_data.get("status") != "requested":
            _logger.warning(
                f"Tool message {self.id} status is not 'requested': {tool_data.get('status')}"
            )
            return self

        tool_call_def = tool_data.get("tool_call")
        if not tool_call_def:
            raise UserError("No tool call definition found in message")

        fn = tool_call_def.get("function", {})
        name = fn.get("name", "unknown_tool")
        args = fn.get("arguments")

        # Emit tool_called event
        yield {
            "type": "tool_called",
            "tool_data": {
                "tool_call_id": tool_data.get("tool_call_id"),
                "tool_name": name,
                "arguments": self._parse_tool_arguments(args) if args else {},
                "status": "executing",
            },
        }

        # Update status to executing
        tool_data["status"] = "executing"
        self.write({"body_json": tool_data})
        yield {"type": "message_update", "message": self.to_store_format()}

        # Execute tool and update message
        try:
            with self.env.cr.savepoint():
                result = self._execute_tool_with_context(name, args, thread_model)
                if result is None:
                    raise UserError(f"No result returned from tool '{name}'")

                # Update tool data with result
                tool_data["status"] = "completed"
                tool_data["result"] = result
                self.write({"body_json": tool_data})

                # Emit tool_succeeded event
                yield {
                    "type": "tool_succeeded",
                    "tool_data": {
                        "tool_call_id": tool_data.get("tool_call_id"),
                        "tool_name": name,
                        "arguments": self._parse_tool_arguments(args) if args else {},
                        "status": "completed",
                        "result": result,
                    },
                }

        except Exception as e:
            _logger.error(f"Error executing tool {name}: {e}")
            # Update tool data with error
            tool_data["status"] = "error"
            tool_data["error"] = str(e)
            self.write({"body_json": tool_data})

            # Emit tool_failed event
            yield {
                "type": "tool_failed",
                "tool_data": {
                    "tool_call_id": tool_data.get("tool_call_id"),
                    "tool_name": name,
                    "arguments": self._parse_tool_arguments(args) if args else {},
                    "status": "error",
                    "error": str(e),
                },
            }

        yield {"type": "message_update", "message": self.to_store_format()}
        return self

    def _validate_tool_call(self, tool_call):
        """Validate tool call structure.

        Args:
            tool_call (dict): Tool call data to validate

        Returns:
            bool: True if valid, False otherwise
        """
        if not isinstance(tool_call, dict):
            _logger.error(f"Tool call is not a dict: {tool_call}")
            return False

        if not tool_call.get("id"):
            _logger.error(f"Tool call missing ID: {tool_call}")
            return False

        function = tool_call.get("function", {})
        if not function.get("name"):
            _logger.error(f"Tool call missing function name: {tool_call}")
            return False

        return True

    def _parse_tool_arguments(self, arguments_str):
        """Parse and validate tool arguments.

        Args:
            arguments_str (str or dict): Tool arguments to parse

        Returns:
            dict: Parsed arguments
        """
        try:
            if isinstance(arguments_str, str):
                return json.loads(arguments_str)
            elif isinstance(arguments_str, dict):
                return arguments_str
            else:
                _logger.warning(f"Unexpected arguments type: {type(arguments_str)}")
                return {}
        except json.JSONDecodeError as e:
            _logger.error(f"Invalid JSON in tool arguments: {arguments_str}")
            raise UserError(f"Invalid tool arguments format: {e}") from e

    def _execute_tool_with_context(self, tool_name, arguments_str, thread_model=None):
        """Execute a tool with proper context.

        Args:
            tool_name (str): Name of the tool to execute
            arguments_str (str): Tool arguments as JSON string
            thread_model (recordset): The thread model that owns this message

        Returns:
            Any: Tool execution result
        """
        if not thread_model:
            # Try to get thread model from message context
            if self.model and self.res_id:
                thread_model = self.env[self.model].browse(self.res_id)
            else:
                raise UserError("No thread model available for tool execution")

        # Find the tool in the thread
        if not hasattr(thread_model, "tool_ids"):
            raise UserError(f"Thread model {thread_model._name} does not support tools")

        tool = thread_model.tool_ids.filtered(lambda t: t.name == tool_name)[:1]
        if not tool:
            raise UserError(f"Tool '{tool_name}' not found in thread")

        # Parse arguments
        arguments = (
            json.loads(arguments_str)
            if isinstance(arguments_str, str)
            else arguments_str
        )

        # Execute with message context
        return tool.with_context(message=self).execute(arguments)

    def create_tool_error_message(self, tool_call, error_msg, thread_model=None):
        """Create an error tool message.

        Args:
            tool_call (dict): Tool call data
            error_msg (str): Error message
            thread_model (recordset): The thread model that owns this message

        Returns:
            mail.message: The created error message
        """
        tool_data = {
            "type": "tool_execution",
            "tool_call_id": tool_call.get("id", "unknown"),
            "tool_call": tool_call,
            "status": "error",
            "error": error_msg,
            "tool_name": tool_call.get("function", {}).get("name", "unknown_tool"),
        }

        if thread_model:
            return thread_model.message_post(
                body_json=tool_data, llm_role="tool", author_id=False
            )
        else:
            return self.env["mail.message"].create(
                {
                    "model": self.model,
                    "res_id": self.res_id,
                    "body_json": tool_data,
                    "subtype_xmlid": "llm.mt_tool",
                    "author_id": False,
                }
            )

    def get_tool_data(self):
        """Get tool data from body_json if this is a tool message.

        Returns:
            dict or None: Tool data if this is a tool message, None otherwise
        """
        self.ensure_one()
        if self.llm_role == "tool" and self.body_json:
            return self.body_json
        return None

    def is_tool_message_with_status(self, status):
        """Check if this is a tool message with a specific status.

        Args:
            status (str): Status to check for ('requested', 'executing', 'completed', 'error')

        Returns:
            bool: True if this is a tool message with the specified status
        """
        self.ensure_one()
        tool_data = self.get_tool_data()
        if not tool_data:
            return False
        return tool_data.get("status") == status
