from odoo import models
from odoo.http import request

from ..file_service import DEFAULT_MAX_UPLOAD_MB


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _pre_dispatch(cls, rule, args):
        # An upload's body *is* the file, but Odoo parses form bodies before
        # the controller runs, and Werkzeug's form parser consumes the stream
        # without caching it. A client that lets curl pick the default content
        # type (``curl --data-binary`` sends application/x-www-form-urlencoded)
        # would therefore hand the controller an empty body.
        #
        # Reading the body here caches it first so get_data() returns the real
        # bytes. If the advertised length already exceeds the limit, leave it
        # unread and let the controller answer 413.
        httprequest = request.httprequest
        if (
            httprequest.method == "PUT"
            and httprequest.path.startswith("/mcp/files/")
            and httprequest.mimetype == "application/x-www-form-urlencoded"
        ):
            max_size = int(
                request.env["ir.config_parameter"]
                .sudo()
                .get_param(
                    "llm_mcp_server.max_file_upload_mb", DEFAULT_MAX_UPLOAD_MB
                )
            ) * 1024 * 1024
            length = httprequest.content_length
            if length is None or length <= max_size:
                httprequest.get_data(cache=True)
        return super()._pre_dispatch(rule, args)
