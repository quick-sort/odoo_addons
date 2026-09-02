import contextlib
import json
import logging

import emoji
import markdown2
from markupsafe import Markup
from psycopg2 import OperationalError

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RelatedRecordProxy:
    """
    A proxy object that provides clean access to related record fields in Jinja templates.
    Usage in templates: {{ related_record.get_field('field_name', 'default_value') }}
    When called directly, returns JSON with model name, id, and display name.
    """

    def __init__(self, record):
        self._record = record

    def get_field(self, field_name, default=""):
        """
        Get a field value from the related record.

        Args:
            field_name (str): The field name to access
            default: Default value if field doesn't exist or is empty

        Returns:
            The field value, or default if not available
        """
        if not self._record:
            return default

        try:
            if hasattr(self._record, field_name):
                value = getattr(self._record, field_name)

                # Handle different field types
                if value is None:
                    return default
                if isinstance(value, bool):
                    return value  # Keep as boolean for Jinja
                if hasattr(value, "name"):  # Many2one field
                    return value.name
                if hasattr(value, "mapped"):  # Many2many/One2many field
                    return value.mapped("name")
                return value
            _logger.debug(
                "Field '%s' not found on record %s",
                field_name,
                self._record,
            )
            return default

        except Exception as e:
            _logger.error(
                "Error getting field '%s' from record: %s",
                field_name,
                e,
            )
            return default

    def __getattr__(self, name):
        """Allow direct attribute access as fallback"""
        return self.get_field(name)

    def __bool__(self):
        """Return True if we have a record"""
        return bool(self._record)

    def __str__(self):
        """When called by itself, return JSON of model name, id, and display name"""
        if not self._record:
            return json.dumps({"model": None, "id": None, "display_name": None})

        return json.dumps(
            {
                "model": self._record._name,
                "id": self._record.id,
                "display_name": getattr(
                    self._record,
                    "display_name",
                    str(self._record),
                ),
            },
        )

    def __repr__(self):
        """Same as __str__ for consistency"""
        return self.__str__()


class LLMThread(models.Model):
    _name = "llm.thread"
    _description = "LLM Chat Thread"
    _inherit = ["mail.thread"]
    _order = "write_date DESC"

    name = fields.Char(
        string="Title",
        required=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
        required=True,
        ondelete="restrict",
    )
    provider_id = fields.Many2one(
        "llm.provider",
        string="Provider",
        required=True,
        ondelete="restrict",
    )
    model_id = fields.Many2one(
        "llm.model",
        string="Model",
        required=True,
        domain="[('provider_id', '=', provider_id), ('model_use', '=', 'chat')]",
        ondelete="restrict",
    )
    active = fields.Boolean(default=True)

    # Updated fields for related record reference
    model = fields.Char(
        string="Related Document Model",
        help="Technical name of the related model",
    )
    res_id = fields.Many2oneReference(
        string="Related Document ID",
        model_field="model",
        help="ID of the related record",
    )

    tool_ids = fields.Many2many(
        "llm.tool",
        string="Available Tools",
        help="Tools that can be used by the LLM in this thread",
    )

    assistant_id = fields.Many2one(
        "llm.assistant",
        string="Assistant",
        ondelete="restrict",
        help="The assistant used for this thread",
    )

    attachment_ids = fields.Many2many(
        "ir.attachment",
        string="All Thread Attachments",
        compute="_compute_attachment_ids",
        store=True,
        help="All attachments from all messages in this thread",
    )

    attachment_count = fields.Integer(
        string="Thread Attachments",
        compute="_compute_attachment_count",
        store=True,
        help="Total number of attachments in this thread",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Set default title if not provided"""
        needs_unique_name = []

        for vals in vals_list:
            if not vals.get("name"):
                # If linked to a record, use its display name
                if vals.get("model") and vals.get("res_id"):
                    try:
                        record = self.env[vals["model"]].browse(vals["res_id"])
                        if record.exists():
                            vals["name"] = f"AI Chat - {record.display_name}"
                        else:
                            # Record doesn't exist, use technical format
                            vals["name"] = f"AI Chat - {vals['model']}#{vals['res_id']}"
                    except Exception:
                        # Model doesn't exist or access error, use technical format
                        vals["name"] = f"AI Chat - {vals['model']}#{vals['res_id']}"
                else:
                    # Generic name - will add unique ID after creation
                    vals["name"] = "New Chat"
                    needs_unique_name.append(True)
            else:
                needs_unique_name.append(False)

        records = super().create(vals_list)

        # Update generic thread names to include unique ID
        for record, needs_update in zip(records, needs_unique_name):
            if needs_update:
                record.name = f"New Chat #{record.id}"

        return records

    @api.depends("message_ids.attachment_ids")
    def _compute_attachment_ids(self):
        """Compute all attachments from all messages in this thread."""
        for thread in self:
            # Get all attachments from all messages in this thread
            all_attachments = thread.message_ids.mapped("attachment_ids")
            thread.attachment_ids = [(6, 0, all_attachments.ids)]

    @api.depends("attachment_ids")
    def _compute_attachment_count(self):
        """Compute the total number of attachments in this thread."""
        for thread in self:
            thread.attachment_count = len(thread.attachment_ids)

    @api.onchange("assistant_id")
    def _onchange_assistant_id(self):
        """Update provider, model and tools when assistant changes"""
        if self.assistant_id:
            self.provider_id = self.assistant_id.provider_id
            self.model_id = self.assistant_id.model_id
            self.tool_ids = self.assistant_id.tool_ids

    def set_assistant(self, assistant_id):
        """Set the assistant for this thread and update related fields

        Args:
            assistant_id (int): The ID of the assistant to set

        Returns:
            bool: True if successful, False otherwise
        """
        self.ensure_one()

        if not assistant_id:
            return self.write({"assistant_id": False})

        # Get the assistant record
        assistant = self.env["llm.assistant"].browse(assistant_id)
        if not assistant.exists():
            return False

        # Update the thread with the assistant and related fields
        update_vals = {
            "assistant_id": assistant_id,
            "tool_ids": [(6, 0, assistant.tool_ids.ids)],
        }
        if assistant.provider_id.id:
            update_vals["provider_id"] = assistant.provider_id.id
        if assistant.model_id.id:
            update_vals["model_id"] = assistant.model_id.id
        return self.write(update_vals)

    def action_open_thread(self):
        """Open the thread in the chat client interface

        Returns:
            dict: Action to open the thread in the chat client
        """
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "llm.chat_client_action",
            "params": {
                "default_active_id": self.id,
            },
            "context": {
                "active_id": self.id,
            },
            "target": "current",
        }

    @api.model
    def get_thread_by_id(self, thread_id):
        """Get a thread record by its ID

        Args:
            thread_id (int): ID of the thread

        Returns:
            tuple: (thread, error_response)
                  If successful, error_response will be None
                  If error, thread will be None
        """
        thread = self.browse(int(thread_id))
        if not thread.exists():
            return None, {"success": False, "error": "Thread not found"}
        return thread, None

    @api.model
    def get_thread_and_assistant(self, thread_id, assistant_id=False):
        """Get thread and assistant records by their IDs

        Args:
            thread_id (int): ID of the thread
            assistant_id (int, optional): ID of the assistant, or False to clear

        Returns:
            tuple: (thread, assistant, error_response)
                  If successful, error_response will be None
                  If error, thread and/or assistant will be None
        """
        # Get thread
        thread, error = self.get_thread_by_id(thread_id)
        if error:
            return None, None, error

        # If no assistant_id, return just the thread
        if not assistant_id:
            return thread, None, None

        # Get assistant from the assistant model
        assistant, error = self.env["llm.assistant"].get_assistant_by_id(assistant_id)
        if error:
            return thread, None, error

        return thread, assistant, None

    # ============================================================================
    # MESSAGE POST OVERRIDES - Clean integration with mail.thread
    # ============================================================================
    # Note: @api.returns removed in Odoo 19 - Odoo infers return type automatically
    def message_post(
        self,
        *,
        llm_role=None,
        message_type="comment",
        body_json=None,
        is_error=False,
        **kwargs,
    ):
        """Override to handle LLM-specific message types and metadata.

        Args:
            llm_role (str): The LLM role ('user', 'assistant', 'tool', 'system')
                           If provided, will automatically set the appropriate subtype
            body_json (dict): JSON body for tool calls - will be set after message creation
            is_error (bool): If True, marks message as error (excluded from LLM context)
        """

        # Convert LLM role to subtype_xmlid if provided
        if llm_role:
            _, role_to_id = self.env["mail.message"].get_llm_roles()
            if llm_role in role_to_id:
                # Get the xmlid from the role
                subtype_xmlid = f"llm.mt_{llm_role}"
                kwargs["subtype_xmlid"] = subtype_xmlid

        # Handle LLM-specific subtypes and email_from generation
        if not kwargs.get("author_id") and not kwargs.get("email_from"):
            kwargs["email_from"] = self._get_llm_email_from(
                kwargs.get("subtype_xmlid"),
                kwargs.get("author_id"),
                llm_role,
            )

        # Convert markdown to HTML if needed (only for assistant messages)
        # User messages should be plain text, tool messages use body_json
        if kwargs.get("body") and llm_role == "assistant":
            kwargs["body"] = self._process_llm_body(kwargs["body"])

        # Create the message using standard mail.thread flow (without body_json)
        message = super().message_post(message_type=message_type, **kwargs)

        # Set additional fields after message creation
        write_vals = {}
        if body_json:
            write_vals["body_json"] = body_json
        if is_error:
            write_vals["is_error"] = True
        if write_vals:
            message.write(write_vals)

        return message

    def _get_llm_email_from(self, subtype_xmlid, author_id, llm_role=None):
        """Generate appropriate email_from for LLM messages."""
        if author_id:
            return None  # Let standard flow handle it

        provider_name = self.provider_id.name
        model_name = self.model_id.name

        if subtype_xmlid == "llm.mt_tool" or llm_role == "tool":
            return f"Tool <tool@{provider_name.lower().replace(' ', '')}.ai>"
        if subtype_xmlid == "llm.mt_assistant" or llm_role == "assistant":
            return f"{model_name} <ai@{provider_name.lower().replace(' ', '')}.ai>"

        return None

    def _process_llm_body(self, body):
        """Process body content for LLM messages (markdown to HTML conversion).

        Skips processing if body is already Markup (pre-formatted HTML).

        Emoji normalization: round-trip through demojize → emojize so that both
        unicode emoji (🔹) and shortcodes (`:small_blue_diamond:`) end up as
        the same unicode emoji in the rendered output. Without the second
        ``emojize`` step, ``demojize`` alone would leave raw ``:shortcode:``
        text in the HTML.
        """
        if not body or isinstance(body, Markup):
            return body
        normalized = emoji.emojize(emoji.demojize(body))
        return markdown2.markdown(normalized, extras=["tables"])

    # ============================================================================
    # STREAMING MESSAGE CREATION
    # ============================================================================

    def message_post_from_stream(
        self,
        stream,
        llm_role,
        placeholder_text="…",
        **kwargs,
    ):
        """Create and update a message from a streaming response.

        Args:
            stream: Generator yielding chunks of response data
            llm_role (str): The LLM role ('user', 'assistant', 'tool', 'system')
            placeholder_text (str): Text to show while streaming

        Returns:
            message: The created/updated message record
        """
        message = None
        accumulated_content = ""

        for chunk in stream:
            # Initialize message on first content
            if message is None and chunk.get("content"):
                message = self.message_post(
                    body=placeholder_text,
                    llm_role=llm_role,
                    author_id=False,
                    **kwargs,
                )
                yield {"type": "message_create", "message": message.to_store_format()}

            # Handle content streaming
            if chunk.get("content"):
                accumulated_content += chunk["content"]
                message.write({"body": self._process_llm_body(accumulated_content)})
                yield {"type": "message_chunk", "message": message.to_store_format()}

            # Handle errors
            if chunk.get("error"):
                yield {"type": "error", "error": chunk["error"]}
                return message

        # Final update for assistant message
        if message and accumulated_content:
            message.write({"body": self._process_llm_body(accumulated_content)})
            yield {"type": "message_update", "message": message.to_store_format()}

        return message

    # ============================================================================
    # GENERATION FLOW - Refactored to use message_post with roles
    # ============================================================================

    def generate(self, user_message_body=None, attachment_ids=None, **kwargs):
        """Main generation method with PostgreSQL advisory locking.

        Args:
            user_message_body: Optional message body. If not provided, will use
                              the latest message in the thread to start generation.
            attachment_ids: Optional list of ir.attachment IDs to attach to user message.
        """
        self.ensure_one()

        with self._generation_lock():
            last_message = False
            if user_message_body or attachment_ids:
                post_kwargs = {
                    "body": user_message_body or "",
                    "llm_role": "user",
                    "author_id": self.env.user.partner_id.id,
                }
                if attachment_ids:
                    post_kwargs["attachment_ids"] = attachment_ids
                last_message = self.message_post(**post_kwargs)
                yield {
                    "type": "message_create",
                    "message": last_message.to_store_format(),
                }

                # Check for unsupported attachments in the new message
                if last_message.attachment_ids:
                    unsupported = self._check_unsupported_attachments(last_message)
                    if unsupported:
                        # Mark the user message as error (excluded from LLM context)
                        last_message.write({"is_error": True})
                        # Show warning and return - don't call LLM
                        yield from self._handle_unsupported_attachments(unsupported)
                        return last_message

            last_message = yield from self.generate_messages(last_message)
            return last_message

    def _get_context_messages(self, limit=25):
        """Get recent LLM messages that will be sent as context.

        This is used to validate attachments in the ENTIRE context before
        sending to the LLM, not just the new message.

        Note: Error messages (is_error=True) are excluded from context.

        Args:
            limit: Maximum number of messages to retrieve (default: 25)

        Returns:
            mail.message recordset of recent LLM messages
        """
        self.ensure_one()
        domain = [
            ("model", "=", self._name),
            ("res_id", "=", self.id),
            ("llm_role", "!=", False),
            ("is_error", "=", False),  # Exclude error messages from context
        ]
        return self.env["mail.message"].search(
            domain,
            order="create_date DESC, id DESC",
            limit=limit,
        )

    def _check_unsupported_attachments(self, message=None):
        """Check a message for unsupported attachments.

        Args:
            message: Specific message to check. If None, checks entire context.

        Returns:
            List of unsupported attachments or empty list
        """
        self.ensure_one()

        if message:
            # Check only the specific message
            messages_to_check = message
        else:
            # Check all context messages (for model switch scenarios)
            context_messages = self._get_context_messages()
            messages_to_check = context_messages.filtered(
                lambda m: m.attachment_ids,
            )

        if not messages_to_check:
            return []

        provider_service = self.provider_id.service
        is_multimodal = self.model_id.supports_image_input

        return messages_to_check._get_unsupported_attachments(
            provider_service=provider_service,
            is_multimodal=is_multimodal,
        )

    def _handle_unsupported_attachments(self, unsupported):
        """Create an info message for unsupported attachments.

        The message has is_error=True so it's excluded from LLM context,
        allowing the conversation to continue normally.

        Args:
            unsupported: List of dicts with name, mimetype, reason

        Yields:
            Message events for the info message
        """
        # Build file list items
        file_items = "".join(
            f"<li><strong>{att['name']}</strong>: {att['reason']}</li>"
            for att in unsupported
        )

        # Build HTML message
        error_html = (
            f"<p>⚠️ <strong>{_('Unsupported file(s)')}</strong></p>"
            f"<ul>{file_items}</ul>"
            f"<p><em>{_('These files will be skipped.')}</em></p>"
        )

        # Post as info message (excluded from LLM context)
        error_message = self.message_post(
            body=Markup(error_html),
            llm_role="assistant",
            author_id=False,
            is_error=True,
        )
        yield {
            "type": "message_create",
            "message": error_message.to_store_format(),
        }
        return error_message

    def _post_error_message(self, error, title=None):
        """Post an error message to the thread (excluded from LLM context).

        This allows users to see API errors directly in the chat instead of
        only in server logs.

        Args:
            error: The exception or error string
            title: Optional title for the error message

        Returns:
            tuple: (error_message, event_dict) for yielding to the client
        """
        title = title or _("Error")
        error_str = str(error)

        # Build HTML error message
        error_html = (
            f"<p>❌ <strong>{title}</strong></p><p><code>{error_str}</code></p>"
        )

        error_message = self.message_post(
            body=Markup(error_html),
            llm_role="assistant",
            author_id=False,
            is_error=True,
        )

        event = {
            "type": "message_create",
            "message": error_message.to_store_format(),
        }
        return error_message, event

    def generate_messages(self, last_message=None):
        """Generate messages with actual AI intelligence.

        Drives the user → assistant → tool round-trip loop for a thread, using
        the assistant's prompt template (if any) and enforcing a cap on
        consecutive tool-call rounds via ``assistant_id.tool_calls_max``.
        """
        self.ensure_one()

        # Get last message if not provided
        if not last_message:
            try:
                last_message = self.get_latest_llm_message()
            except UserError:
                # No DB messages found - check if prepended messages have a user message
                prepend_msgs = self.get_prepend_messages()
                user_msg = next(
                    (msg for msg in prepend_msgs if msg.get("role") == "user"),
                    None,
                )

                if user_msg:
                    # Extract content from prepended user message
                    content = user_msg.get("content", [])
                    if isinstance(content, list) and content:
                        body = content[0].get("text", "")
                    else:
                        body = str(content)

                    # Create actual user message from prepended content
                    last_message = self.message_post(
                        body=body,
                        llm_role="user",
                        author_id=self.env.user.partner_id.id,
                    )
                else:
                    # No user message in prepended messages either
                    raise

        # Cap on consecutive assistant→tool→assistant rounds. Without it the
        # model can spam tool calls indefinitely.
        tool_call_rounds = 0
        max_tool_call_rounds = (
            self.assistant_id.tool_calls_max if self.assistant_id else 0
        )

        # Continue generation loop
        while self._should_continue(last_message):
            if last_message.llm_role in ("user", "tool"):
                if self.model_id.model_use in ("image_generation", "generation"):
                    last_message = yield from self._generate_response(last_message)
                else:
                    # Generate assistant response
                    last_message = yield from self._generate_assistant_response()
            elif last_message.llm_role == "assistant" and last_message.has_tool_calls():
                # Execute ALL tool calls from assistant message
                tool_calls = last_message.get_tool_calls()
                for tool_call in tool_calls:
                    tool_message = yield from self._execute_tool_call(
                        tool_call,
                        last_message,
                    )
                    last_message = tool_message
                    # Flush so the next LLM round-trip sees the tool result.
                    # Commit cadence is the caller's responsibility (HTTP controller
                    # commits on SSE events; queue_job commits at job end; nested
                    # tool callers may run inside a savepoint).
                    self.env.flush_all()

                tool_call_rounds += 1
                if max_tool_call_rounds and tool_call_rounds >= max_tool_call_rounds:
                    assistant_label = (
                        self.assistant_id.code or self.assistant_id.name
                        if self.assistant_id else "<no assistant>"
                    )
                    _logger.warning(
                        "[generate_messages] thread_id=%d assistant=%r hit "
                        "tool_calls_max=%d after %d round(s); breaking loop. "
                        "The model will not be called again for this turn.",
                        self.id, assistant_label,
                        max_tool_call_rounds, tool_call_rounds,
                    )
                    yield {
                        "type": "limit_reached",
                        "reason": "tool_calls_max",
                        "limit": max_tool_call_rounds,
                        "rounds_executed": tool_call_rounds,
                    }
                    break
            else:
                _logger.info(
                    f"Breaking loop. Last message role: {last_message.llm_role}, "
                    f"has_tool_calls: {last_message.has_tool_calls()}",
                )
                break

        return last_message

    def _generate_response(self, last_message):
        raise NotImplementedError

    def _generate_assistant_response(self):
        """Generate assistant response and handle tool calls.

        Catches LLM API errors and posts them as error messages in the thread
        so users can see what went wrong without checking server logs.
        """
        # Flush any pending writes to ensure latest messages are visible
        self.env.flush_all()

        # Use the new optimized method for LLM context
        message_history = self.get_llm_messages()

        # Determine if we should use streaming
        use_streaming = getattr(self.model_id, "supports_streaming", True)

        chat_kwargs = self._prepare_chat_kwargs(message_history, use_streaming)

        try:
            if use_streaming:
                # Handle streaming response - process tool calls directly from stream
                stream_response = self.sudo().model_id.chat(**chat_kwargs)
                assistant_message = yield from self._handle_streaming_response(
                    stream_response,
                )
            else:
                # Handle non-streaming response
                response = self.sudo().model_id.chat(**chat_kwargs)
                assistant_message = yield from self._handle_non_streaming_response(
                    response,
                )
        except Exception as e:
            # Post error message to thread so user can see it
            _logger.exception("LLM API error in thread %s", self.id)
            error_message, event = self._post_error_message(
                e,
                title=_("LLM API Error"),
            )
            yield event
            return error_message

        return assistant_message

    def _prepare_chat_kwargs(self, message_history, use_streaming):
        """Prepare chat kwargs for provider. Can be overridden by extensions."""
        return {
            "messages": message_history,
            "tools": self.tool_ids,
            "stream": use_streaming,
            "prepend_messages": self.get_prepend_messages(),
        }

    def get_llm_messages(self, limit=25):
        """Get the most recent LLM messages in chronological order.

        This method is optimized for LLM context preparation:
        - Always returns messages in chronological order (ASC)
        - Limits to the most recent N messages for context window management
        - Uses efficient database queries with proper indexing
        - Excludes error messages (is_error=True) from context

        Args:
            limit (int): Maximum number of recent messages to retrieve (default: 25)

        Returns:
            mail.message recordset: Recent LLM messages in chronological order
        """
        self.ensure_one()

        # Domain for filtering LLM messages only (excluding error messages)
        domain = [
            ("model", "=", self._name),
            ("res_id", "=", self.id),
            ("llm_role", "!=", False),  # Only messages with LLM roles
            ("is_error", "=", False),  # Exclude error messages from LLM context
        ]

        if limit:
            # Two-step approach for efficiency:
            # 1. Get the N most recent messages (DESC order)
            recent_messages = self.env["mail.message"].search(
                domain,
                order="create_date DESC, write_date DESC, id DESC",
                limit=limit,
            )
            # 2. Sort them chronologically for LLM context (ASC order)
            return recent_messages.sorted(lambda m: (m.create_date, m.write_date, m.id))
        # If no limit, get all messages in chronological order
        return self.env["mail.message"].search(
            domain,
            order="create_date ASC, write_date ASC, id ASC",
        )

    def get_latest_llm_message(self):
        """Get the most recent LLM message for flow control.

        Returns:
            mail.message: The latest LLM message

        Raises:
            UserError: If no LLM messages exist
        """
        self.ensure_one()

        domain = [
            ("model", "=", self._name),
            ("res_id", "=", self.id),
            ("llm_role", "!=", False),
        ]

        result = self.env["mail.message"].search(
            domain,
            order="create_date DESC, write_date DESC, id DESC",
            limit=1,
        )

        if not result:
            raise UserError("No LLM messages found in this thread.")

        return result[0]

    def _should_continue(self, last_message):
        """Simplified continue logic based on message history."""
        if not last_message:
            return False

        # Continue if:
        # 1. Last message is user message → generate assistant response
        # 2. Last message is tool message → generate assistant response
        # 3. Last message is assistant with tool calls → execute tools
        if last_message.llm_role in ("user", "tool") or (
            last_message.llm_role == "assistant" and last_message.has_tool_calls()
        ):
            return True

        return False

    def _handle_streaming_response(self, stream_response):
        """Handle streaming response from LLM provider with tool call processing."""
        message = None
        accumulated_content = ""
        collected_tool_calls = []
        collected_images = []

        for chunk in stream_response:
            # Initialize message on first content
            if message is None and chunk.get("content"):
                message = self.message_post(
                    body="Thinking...",
                    llm_role="assistant",
                    author_id=False,
                )
                yield {"type": "message_create", "message": message.to_store_format()}

            # Handle content streaming
            if chunk.get("content"):
                accumulated_content += chunk["content"]
                message.write({"body": self._process_llm_body(accumulated_content)})
                yield {"type": "message_chunk", "message": message.to_store_format()}

            # Collect tool calls for processing
            if chunk.get("tool_calls"):
                collected_tool_calls.extend(chunk["tool_calls"])
                _logger.debug(
                    f"Collected {len(chunk['tool_calls'])} tool calls from chunk",
                )

            # Collect images from stream
            if chunk.get("images"):
                collected_images.extend(chunk["images"])

            # Handle errors
            if chunk.get("error"):
                yield {"type": "error", "error": chunk["error"]}
                return message

        # Build body_json — preserve raw markdown content alongside any
        # tool_calls so callers (invoke / dispatch result extraction) can get
        # the un-HTMLified text back without round-tripping through html2text.
        body_json = {}
        if accumulated_content:
            body_json["content"] = accumulated_content
        if collected_tool_calls:
            body_json["tool_calls"] = collected_tool_calls

        if collected_tool_calls:
            if not message:
                # Create assistant message with body_json (handled by message_post override)
                message = self.message_post(
                    body="",  # Empty body for tool-only responses
                    body_json=body_json,
                    llm_role="assistant",
                    author_id=False,
                )
                # Flush so the about-to-execute tool can read the message via SQL.
                self.env.flush_all()
                yield {"type": "message_create", "message": message.to_store_format()}
            else:
                # Update existing message with tool calls (and raw content if any)
                message.write({"body_json": body_json})
                self.env.flush_all()
                yield {"type": "message_update", "message": message.to_store_format()}
        elif message and accumulated_content:
            # Final update for assistant message without tool calls — write
            # both the rendered HTML body (for UI) and the raw markdown content
            # (in body_json, for programmatic callers).
            message.write({
                "body": self._process_llm_body(accumulated_content),
                "body_json": body_json,
            })
            yield {"type": "message_update", "message": message.to_store_format()}

        # Save images as attachments on the message
        if collected_images and message:
            self._save_response_images(collected_images, message)
            yield {"type": "message_update", "message": message.to_store_format()}

        return message

    def _handle_non_streaming_response(self, response):
        """Handle non-streaming response from LLM provider."""
        # Extract content and tool calls from response
        content = response.get("content", "")
        tool_calls = response.get("tool_calls", [])
        images = response.get("images", [])

        if not content and not tool_calls and not images:
            content = "No response from model"

        # body_json carries raw markdown content (for programmatic callers)
        # and/or tool_calls.
        body_json = {}
        if content:
            body_json["content"] = content
        if tool_calls:
            body_json["tool_calls"] = tool_calls

        # Create assistant message with body_json (handled by message_post override)
        assistant_message = self.message_post(
            body=self._process_llm_body(content) if content else "",
            body_json=body_json or None,
            llm_role="assistant",
            author_id=False,
        )

        if images:
            self._save_response_images(images, assistant_message)

        yield {
            "type": "message_create",
            "message": assistant_message.to_store_format(),
        }
        return assistant_message

    def _save_response_images(self, images, message):
        """Save LLM-generated images as attachments on the given message.

        Args:
            images: List of dicts with keys 'mimetype', 'data' (base64), and
                    optionally 'url' (external URL).
            message: mail.message record to attach images to.
        """
        attachments = self.env["ir.attachment"]
        for idx, img in enumerate(images):
            mimetype = img.get("mimetype", "image/png")
            ext = mimetype.split("/")[-1] if "/" in mimetype else "png"
            vals = {
                "name": f"generated_image_{idx}.{ext}",
                "res_model": "mail.message",
                "res_id": message.id,
                "mimetype": mimetype,
            }
            if img.get("data"):
                vals["datas"] = img["data"]
            elif img.get("url"):
                vals["url"] = img["url"]
                vals["type"] = "url"
            else:
                continue
            attachments |= self.env["ir.attachment"].create(vals)
        if attachments:
            message.write({"attachment_ids": [(4, a.id) for a in attachments]})

    def _execute_tool_call(self, tool_call, assistant_message):
        """Execute a single tool call and return the tool message.

        Args:
            tool_call (dict): Tool call data from assistant message
            assistant_message (mail.message): The assistant message that contains the tool calls

        Yields:
            dict: Status updates for streaming

        Returns:
            mail.message: The tool message with execution result
        """
        try:
            # Create tool message using the post_tool_call method
            tool_msg = self.env["mail.message"].post_tool_call(
                tool_call,
                thread_model=self,
            )
            yield {"type": "message_create", "message": tool_msg.to_store_format()}

            # Execute the tool call
            result_msg = yield from tool_msg.execute_tool_call(thread_model=self)
            return result_msg

        except Exception as e:
            _logger.error(f"Error executing tool call: {e}")

            # Create error tool message using the new method
            try:
                error_msg = self.env["mail.message"].create_tool_error_message(
                    tool_call,
                    str(e),
                    thread_model=self,
                )
                yield {
                    "type": "message_create",
                    "message": error_msg.to_store_format(),
                }
                return error_msg
            except Exception as e2:
                _logger.error(f"Failed to create error message: {e2}")
                # Yield error event so frontend knows something went wrong
                yield {
                    "type": "error",
                    "error": f"Tool execution failed: {e!s}",
                }
                # Re-raise the original exception - don't silently return None
                raise e from e2

    def _extract_message_content(self, message):
        """Extract text content from a message regardless of format"""
        content = message.get("content", "")

        if isinstance(content, list) and len(content) > 0:
            return content[0].get("text", "")
        if isinstance(content, str):
            return content
        return ""

    def get_prepend_messages(self):
        """Hook: return a list of formatted messages to prepend to the conversation.

        If the thread has an assistant, renders its prompt template (via
        ``llm.assistant.get_messages``) using the thread context, which
        already carries the evaluated default values.
        """
        self.ensure_one()

        if self.assistant_id:
            try:
                return self.assistant_id.get_messages(self.get_context())
            except Exception as e:
                _logger.error(
                    "Error rendering the prompt of assistant '%s': %s",
                    self.assistant_id.name,
                    e,
                )
                # Continue without the prompt rather than failing the whole
                # conversation, but tell the user.
                self.message_post(
                    body=_(
                        "Note: the prompt of assistant '%s' could not be "
                        "rendered. Continuing without it. (Error: %s)",
                    )
                    % (self.assistant_id.name, str(e)),
                )

        return []

    def get_context(self, base_context=None):
        context = {
            **(base_context or {}),
            "thread_id": self.id,
        }
        # Guard clause: skip if model or res_id not set
        if not self.model or not self.res_id:
            related_record = None
        else:
            related_record = None
            try:
                candidate = self.env[self.model].browse(self.res_id)
                if candidate:
                    related_record = candidate
                    context["related_record"] = RelatedRecordProxy(candidate)
                    context["related_model"] = self.model
                    context["related_res_id"] = self.res_id
                else:
                    context["related_record"] = None
                    context["related_model"] = None
                    context["related_res_id"] = None
            except Exception as e:
                _logger.warning(
                    "Error accessing related record %s,%s: %s",
                    self.model,
                    self.res_id,
                    e,
                )

        # If we have an assistant with default values, add them to the context.
        # Assistant defaults are added first, so the base context (built above)
        # takes precedence.
        if self.assistant_id:
            assistant_defaults = self.assistant_id.get_evaluated_default_values(
                context
            )
            if assistant_defaults:
                context = {**assistant_defaults, **context}

        return context

    # ============================================================================
    # POSTGRESQL ADVISORY LOCK IMPLEMENTATION
    # ============================================================================

    def _acquire_thread_lock(self):
        """Acquire PostgreSQL advisory lock for this thread."""
        self.ensure_one()

        try:
            query = "SELECT pg_try_advisory_lock(%s)"
            self.env.cr.execute(query, (self.id,))
            result = self.env.cr.fetchone()

            if not result or not result[0]:
                raise UserError(
                    _(
                        "This conversation is currently generating a response. "
                        "Please wait for it to complete before sending another message.",
                    ),
                )

            _logger.info(f"Acquired advisory lock for thread {self.id}")

        except UserError:
            raise
        except OperationalError as e:
            _logger.error("Database error acquiring lock for thread %s: %s", self.id, e)
            raise UserError(
                _(
                    "Unable to process your request due to a system conflict. "
                    "Please wait a moment and try again.",
                ),
            ) from e
        except Exception as e:
            _logger.error(
                "Unexpected error acquiring lock for thread %s: %s",
                self.id,
                e,
            )
            raise UserError(
                _(
                    "Your request could not be processed. Please refresh the page and try again.",
                ),
            ) from e

    def _release_thread_lock(self):
        """Release PostgreSQL advisory lock for this thread."""
        self.ensure_one()

        try:
            query = "SELECT pg_advisory_unlock(%s)"
            self.env.cr.execute(query, (self.id,))
            result = self.env.cr.fetchone()

            success = result and result[0]
            if success:
                _logger.info(f"Released advisory lock for thread {self.id}")
            else:
                _logger.warning(f"Advisory lock for thread {self.id} was not held")

            return success

        except Exception as e:
            _logger.error(f"Error releasing lock for thread {self.id}: {e}")
            return False

    @contextlib.contextmanager
    def _generation_lock(self):
        """Context manager for thread generation with automatic lock cleanup."""
        self.ensure_one()

        self._acquire_thread_lock()

        try:
            _logger.info(f"Starting locked generation for thread {self.id}")
            yield self

        finally:
            released = self._release_thread_lock()
            if released:
                _logger.info(f"Finished locked generation for thread {self.id}")
            else:
                _logger.warning(f"Lock release failed for thread {self.id}")

    # ============================================================================
    # ODOO HOOKS AND CLEANUP
    # ============================================================================

    # ============================================================================
    # STORE INTEGRATION - For mail.store compatibility
    # ============================================================================

    def _thread_to_store(self, store, fields=None, **kwargs):
        """Extend base _thread_to_store to include LLM-specific fields."""
        super()._thread_to_store(store, fields=fields, **kwargs)

        # Add LLM-specific thread data
        for thread in self:
            # Build the data dict with only the fields we need
            thread_data = {
                "id": thread.id,
                "model": "llm.thread",
                "name": thread.name,  # Essential for UI display
                "write_date": thread.write_date,  # For sorting in thread list
                "channel_type": "llm_chat",  # Custom type for LLM threads
                "assistant_id": {
                    "id": thread.assistant_id.id,
                    "name": thread.assistant_id.name,
                    "model": "llm.assistant",
                }
                if thread.assistant_id
                else False,
            }

            # Related record fields (for linking threads to Odoo records)
            # Use res_model to avoid conflict with "model": "llm.thread"
            if thread.model:
                thread_data["res_model"] = thread.model
            if thread.res_id:
                thread_data["res_id"] = thread.res_id

            # Add LLM-specific fields using proper Store.one/Store.many format
            # sudo() is required: these config models restrict read access to
            # LLM Manager/User groups, but any user running a workflow that
            # creates an llm.thread needs their display names for the UI.
            if thread.provider_id:
                provider = thread.provider_id.sudo()
                thread_data["provider_id"] = {
                    "id": provider.id,
                    "name": provider.name,
                    "model": "llm.provider",
                }

            if thread.model_id:
                model = thread.model_id.sudo()
                thread_data["model_id"] = {
                    "id": model.id,
                    "name": model.name,
                    "model": "llm.model",
                }

            if thread.tool_ids:
                thread_data["tool_ids"] = [
                    {"id": tool.id, "name": tool.name, "model": "llm.tool"}
                    for tool in thread.tool_ids.sudo()
                ]

            store.add_model_values("mail.thread", thread_data)

    @api.ondelete(at_uninstall=False)
    def _unlink_llm_thread(self):
        unlink_ids = [record.id for record in self]
        self.env["bus.bus"]._sendone(
            self.env.user.partner_id,
            "llm.thread/delete",
            {"ids": unlink_ids},
        )
