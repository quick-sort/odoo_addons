from werkzeug.exceptions import BadRequest, NotFound

from odoo import http
from odoo.http import request


class MicrosoftGraphOAuthController(http.Controller):
    @http.route(
        "/microsoft_graph/connect/<int:application_id>",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def microsoft_graph_connect(self, application_id, redirect=None, **kwargs):
        application = (
            request.env["microsoft.graph.application"]
            .sudo()
            .browse(application_id)
            .exists()
        )
        if not application or not application.allow_user_authorization:
            raise NotFound()
        service = request.env["microsoft.graph.service"]
        if redirect:
            redirect = service._sanitize_post_auth_redirect(redirect)
        action = service._authorization_action(application, redirect_to=redirect)
        return request.redirect(action["url"])

    @http.route(
        "/microsoft_graph/oauth/callback",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def microsoft_graph_oauth_callback(
        self, state=None, code=None, error=None, **kwargs
    ):
        if error:
            raise BadRequest(kwargs.get("error_description") or error)
        if not state or not code:
            raise BadRequest(
                "Missing Microsoft OAuth state or authorization code"
            )
        try:
            credential = request.env[
                "microsoft.graph.service"
            ]._complete_authorization(state, code, request.env.user)
        except Exception as exc:
            raise BadRequest(str(exc)) from exc
        redirect_to = credential.post_auth_redirect
        if request.env.user.has_group("base.group_system"):
            if not redirect_to:
                redirect_to = (
                    f"/web#id={credential.application_id.id}"
                    "&model=microsoft.graph.application&view_type=form"
                )
            return request.redirect(redirect_to)
        return request.redirect("/odoo")
