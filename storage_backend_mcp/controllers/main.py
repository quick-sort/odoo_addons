import hashlib
import json

from odoo import http
from odoo.http import request
from werkzeug.wrappers import Response


class StorageMcpRelay(http.Controller):

    @http.route(
        "/storage_mcp/t/<string:token>", type="http", auth="none", csrf=False,
        methods=["PUT", "GET"],
    )
    def relay(self, token, **kw):
        # The token is the credential: the agent's curl has no MCP API key, and
        # the path is resolved server-side from the token, never from the URL.
        rec = request.env["storage.mcp.token"].sudo()._find_by_raw(token)
        if not rec:
            return Response("Not found", status=404)
        if not rec._use_once():
            return Response("Token already used", status=403)

        if request.httprequest.method == "PUT":
            return self._handle_put(rec)
        return self._handle_get(rec)

    def _handle_put(self, rec):
        backend = rec.backend_id.sudo()
        max_size = rec.max_size_bytes or 0
        # Odoo 19's HTTPRequest does not expose a streaming body reader, so the
        # body is read in one go; the size cap still rejects oversized uploads.
        data = request.httprequest.get_data()
        if max_size and len(data) > max_size:
            return Response("Payload too large", status=413)

        digest = hashlib.sha256(data).hexdigest()
        with backend.open(rec.relative_path, "wb") as stream:
            stream.write(data)

        if rec.upload_id:
            rec.upload_id.sudo().write({
                "sha256": digest,
                "size_bytes": len(data),
            })
        return Response(
            json.dumps({"size": len(data), "sha256": digest}),
            mimetype="application/json",
        )

    def _handle_get(self, rec):
        backend = rec.backend_id.sudo()
        with backend.open(rec.relative_path, "rb") as stream:
            data = stream.read()
        return Response(data, mimetype="application/octet-stream")
