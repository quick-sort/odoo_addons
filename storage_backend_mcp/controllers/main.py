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

        # A multipart body is an envelope around the file, not the file: the
        # relay would store the boundary headers and form fields too. There is
        # no unambiguous "the file" to pick out, so refuse rather than write a
        # corrupted blob. Checked before the token is spent, so the caller can
        # retry the same URL with the raw-body form.
        if (
            request.httprequest.method == "PUT"
            and request.httprequest.mimetype == "multipart/form-data"
        ):
            return Response(
                "Multipart uploads are not supported; send the file as the "
                "raw request body (curl -T <file>).",
                status=415,
            )

        if not rec._use_once():
            return Response("Token already used", status=403)

        if request.httprequest.method == "PUT":
            return self._handle_put(rec)
        return self._handle_get(rec)

    def _handle_put(self, rec):
        backend = rec.backend_id.sudo()
        max_size = rec.max_size_bytes or 0

        # Reject before reading the body when the client advertises a length,
        # so an oversized upload never buffers in memory. Odoo 19's HTTPRequest
        # exposes no streaming body reader, so the body is otherwise read in one
        # go below; the size is re-checked as a chunked-transfer fallback.
        content_length = request.httprequest.content_length
        if max_size and content_length is not None and content_length > max_size:
            return Response("Payload too large", status=413)

        data = request.httprequest.get_data()
        if max_size and len(data) > max_size:
            return Response("Payload too large", status=413)
        # Never turn a body the HTTP layer already swallowed into a successful
        # empty upload: the caller would commit a zero-byte file believing it
        # sent content.
        if content_length and not data:
            return Response(
                "Empty body received; send the file as the raw request body "
                "(curl -T <file>).",
                status=400,
            )

        digest = hashlib.sha256(data).hexdigest()
        with backend.open(rec.relative_path, "wb") as out:
            out.write(data)

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
