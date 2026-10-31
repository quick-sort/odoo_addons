import hashlib
import json

from odoo import fields, http
from odoo.http import request
from odoo.tools.misc import verify_limited_field_access_token
from werkzeug.wrappers import Response

from ..file_service import DEFAULT_MAX_UPLOAD_MB, UPLOAD_SCOPE


class LLMMCPFileRelay(http.Controller):

    @http.route(
        "/mcp/files/<int:attachment_id>", type="http", auth="none", csrf=False,
        methods=["PUT"], readonly=False,
    )
    def upload(self, attachment_id, **kw):
        # The signed token is the credential: the agent's curl has no MCP API
        # key. It is scoped to this attachment and carries its own expiry.
        token = request.httprequest.args.get("access_token")
        attachment = request.env["ir.attachment"].sudo().browse(attachment_id).exists()
        if not attachment:
            return Response("Not found", status=404)
        if not token or not verify_limited_field_access_token(
            attachment, "raw", token, scope=UPLOAD_SCOPE
        ):
            return Response("Forbidden", status=403)

        upload = request.env["llm.mcp.file.upload"].sudo().search(
            [("attachment_id", "=", attachment.id)], order="id desc", limit=1
        )
        if (
            not upload
            or upload.state == "expired"
            or upload.expires_at < fields.Datetime.now()
        ):
            return Response("Upload expired", status=410)

        # A multipart body is an envelope around the file, not the file itself.
        # Refuse before consuming the staging row so the caller can retry with
        # the raw-body form (curl -T <file>).
        if request.httprequest.mimetype == "multipart/form-data":
            return Response(
                "Multipart uploads are not supported; send the file as the "
                "raw request body (curl -T <file>).",
                status=415,
            )

        max_size = int(
            request.env["ir.config_parameter"].sudo().get_param(
                "llm_mcp_server.max_file_upload_mb", DEFAULT_MAX_UPLOAD_MB
            )
        ) * 1024 * 1024
        content_length = request.httprequest.content_length
        if content_length is not None and content_length > max_size:
            return Response("Payload too large", status=413)

        data = request.httprequest.get_data()
        if len(data) > max_size:
            return Response("Payload too large", status=413)
        # Never turn a body the HTTP layer already swallowed into a successful
        # empty upload. An explicit Content-Length: 0 is a legitimate empty file.
        if content_length and not data:
            return Response(
                "Empty body received; send the file as the raw request body "
                "(curl -T <file>).",
                status=400,
            )

        # Claim only after the body is validated, so rejected requests leave
        # the staging row reusable. The claim is atomic: concurrent or replayed
        # PUTs fail here.
        if not upload._claim_upload():
            return Response("Upload already consumed", status=409)

        digest = hashlib.sha256(data).hexdigest()
        # image_no_postprocess keeps the uploaded bytes intact (core would
        # otherwise downscale large images). Writing `raw` avoids base64.
        attachment.sudo().with_context(image_no_postprocess=True).write({
            "raw": data,
            "mimetype": attachment.mimetype,
        })
        upload.write({"sha256": digest, "size_bytes": len(data)})
        return Response(
            json.dumps({"size": len(data), "sha256": digest}),
            mimetype="application/json",
        )
