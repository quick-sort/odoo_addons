import json
import logging

from odoo import _, api, http
from odoo.exceptions import MissingError
from odoo.http import Response, request
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


class LLMThreadController(http.Controller):
    @http.route(
        "/llm/thread/<int:thread_id>/update",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def llm_thread_update(self, thread_id, **kwargs):
        try:
            thread = request.env["llm.thread"].browse(thread_id)
            if not thread.exists():
                raise MissingError(_("LLM Thread not found."))
            thread.write(kwargs)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _safe_yield(data_to_yield):
        """Helper generator to yield data safely, handling BrokenPipeError(Disconnected user)."""
        try:
            yield data_to_yield
            return True
        except BrokenPipeError:
            return False
        except Exception:
            return False

    # Event types that represent a meaningful, low-frequency state change worth
    # committing for. Committing fires bus notifications so other tabs / thread
    # followers see progress in real time. message_chunk is excluded because it
    # is emitted many times per second during streaming.
    _COMMIT_ON_EVENT_TYPES = frozenset({
        "message_create",
        "message_update",
        "tool_called",
        "tool_succeeded",
        "tool_failed",
        "error",
    })

    @classmethod
    def _llm_thread_generate(cls, dbname, env, thread_id, user_message_body, **kwargs):
        """Generate LLM responses with streaming and safe yielding.

        The transaction boundary for the whole LLM turn lives here. `llm.thread`
        and `llm.assistant` deliberately never commit inside `generate_messages`
        — they only flush — so this controller is the single point that decides
        commit cadence for the HTTP/SSE path.
        """
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, env.uid, env.context)
            llm_thread = env["llm.thread"].browse(int(thread_id))
            if not llm_thread.exists():
                yield from cls._safe_yield(
                    f"data: {json.dumps({'type': 'error', 'error': 'LLM Thread not found.'})}\n\n".encode(),
                )
                return

            client_connected = True
            try:
                for response in llm_thread.generate(user_message_body, **kwargs):
                    json_data = json.dumps(response, default=str)
                    success = yield from cls._safe_yield(
                        f"data: {json_data}\n\n".encode(),
                    )
                    if not success:
                        client_connected = False
                        break

                    if response.get("type") in cls._COMMIT_ON_EVENT_TYPES:
                        cr.commit()

            except GeneratorExit:
                client_connected = False

            except Exception as e:
                _logger.exception(
                    f"Error in llm_thread_generate for thread {thread_id}: {e}",
                )
                # Lock will be automatically released by context manager

                if client_connected:
                    success = yield from cls._safe_yield(
                        f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n".encode(),
                    )
                    if not success:
                        client_connected = False

            finally:
                if client_connected:
                    yield from cls._safe_yield(
                        f"data: {json.dumps({'type': 'done'})}\n\n".encode(),
                    )

    @http.route("/llm/thread/generate", type="http", auth="user", csrf=True)
    def llm_thread_generate(
        self,
        thread_id,
        message=None,
        attachment_ids=None,
        **kwargs,
    ):
        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
        parsed_attachment_ids = []
        if attachment_ids:
            parsed_attachment_ids = [
                int(x) for x in attachment_ids.split(",") if x.strip().isdigit()
            ]
        return Response(
            self._llm_thread_generate(
                request.cr.dbname,
                request.env,
                thread_id,
                message,
                attachment_ids=parsed_attachment_ids,
                **kwargs,
            ),
            direct_passthrough=True,
            headers=headers,
        )



class LLMAssistantController(http.Controller):
    @http.route("/llm/thread/set_assistant", type="jsonrpc", auth="user")
    def set_thread_assistant(self, thread_id, assistant_id=False):
        """Set the assistant for a thread and return thread-specific evaluated default values

        Args:
            thread_id (int): ID of the thread to update
            assistant_id (int, optional): ID of the assistant to set, or False to clear

        Returns:
            dict: Result of the operation with evaluated default values if successful
        """
        # Get thread and assistant using the model method
        thread, assistant, error = request.env["llm.thread"].get_thread_and_assistant(
            thread_id, assistant_id
        )
        if error:
            return error

        # Set the assistant on the thread
        result = thread.set_assistant(assistant_id if assistant else False)

        # Return basic result if no assistant was set or operation failed
        if not assistant or not result:
            return {
                "success": bool(result),
                "thread_id": thread_id,
                "assistant_id": assistant_id if assistant else False,
            }

        # Get assistant values with the thread context using the model method
        return assistant.get_assistant_values(thread)

    @http.route("/llm/thread/get_assistant_values", type="jsonrpc", auth="user")
    def get_thread_assistant_values(self, thread_id, assistant_id):
        """Get thread-specific evaluated default values for an assistant

        Args:
            thread_id (int): ID of the thread
            assistant_id (int): ID of the assistant

        Returns:
            dict: Result with evaluated default values
        """
        # Get thread and assistant using the model method
        thread, assistant, error = request.env["llm.thread"].get_thread_and_assistant(
            thread_id, assistant_id
        )
        if error:
            return error

        # Get assistant values with the thread context using the model method
        return assistant.get_assistant_values(thread)
