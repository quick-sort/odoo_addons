from werkzeug.exceptions import BadRequest, NotFound

from odoo import http
from odoo.http import request


class SharePointOAuthController(http.Controller):
    @http.route(
        "/storage_backend_sharepoint/connect/<int:backend_id>",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def sharepoint_oauth_connect(self, backend_id):
        backend = request.env["storage.backend"].sudo().browse(backend_id).exists()
        if (
            not backend
            or backend.backend_type != "sharepoint"
            or not backend.sharepoint_allow_user_authorization
        ):
            raise NotFound()
        action = request.env[
            "sharepoint.graph.service"
        ]._authorization_action(backend)
        return request.redirect(action["url"])

    @http.route(
        "/storage_backend_sharepoint/oauth/callback",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def sharepoint_oauth_callback(self, state=None, code=None, error=None, **kwargs):
        if error:
            raise BadRequest(kwargs.get("error_description") or error)
        if not state or not code:
            raise BadRequest("Missing SharePoint OAuth state or authorization code")
        try:
            backend = request.env[
                "sharepoint.graph.service"
            ]._complete_authorization(state, code, request.env.user)
        except Exception as exc:
            raise BadRequest(str(exc)) from exc
        if request.env.user.has_group("base.group_system"):
            return request.redirect(
                f"/web#id={backend.id}&model=storage.backend&view_type=form"
            )
        return request.redirect("/odoo")
