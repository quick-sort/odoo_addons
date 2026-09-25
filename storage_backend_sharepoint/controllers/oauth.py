from werkzeug.exceptions import NotFound

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
            or not backend.sharepoint_application_id
        ):
            raise NotFound()
        application = backend.sharepoint_application_id
        if not application.allow_user_authorization:
            raise NotFound()
        action = request.env["microsoft.graph.service"]._authorization_action(
            application,
            redirect_to=f"/web#id={backend.id}&model=storage.backend&view_type=form",
        )
        return request.redirect(action["url"])
