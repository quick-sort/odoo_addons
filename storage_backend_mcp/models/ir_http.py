from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _pre_dispatch(cls, rule, args):
        # A relay upload's body *is* the file, but Odoo parses form bodies
        # into ``request.form`` before the controller runs, and Werkzeug's
        # form parser consumes the stream without caching it. A client that
        # lets curl pick the default content type (``curl --data-binary``
        # sends application/x-www-form-urlencoded) would therefore hand the
        # controller an empty body and get a successful zero-byte upload.
        #
        # Reading the body here caches it first. The form parser then works
        # off that cache, and ``get_data()`` in the controller returns the
        # real bytes.
        httprequest = request.httprequest
        if (
            httprequest.method == "PUT"
            and httprequest.path.startswith("/storage_mcp/t/")
            and httprequest.mimetype == "application/x-www-form-urlencoded"
        ):
            # Keep the controller's early size check meaningful: if the
            # advertised length already exceeds the relay maximum, leave the
            # body unread and let the controller answer 413.
            max_size = int(
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("storage_backend_mcp.max_relay_size_mb", "2047")
            ) * 1024 * 1024
            length = httprequest.content_length
            if length is None or length <= max_size:
                httprequest.get_data(cache=True)
        return super()._pre_dispatch(rule, args)
