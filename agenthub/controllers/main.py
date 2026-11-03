import hmac

from odoo import http
from odoo.http import request


class AgenthubRelayConfigController(http.Controller):
    @http.route(
        "/agenthub/relay/config",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def relay_config(self, **kwargs):
        params = request.env["ir.config_parameter"].sudo()
        expected = params.get_param("agenthub.relay_config_token")
        if not expected:
            return request.make_json_response(
                {"error": "relay config token is not configured"}, status=503
            )
        provided = request.httprequest.headers.get(
            "X-AgentHub-Config-Token", ""
        )
        if not hmac.compare_digest(provided, expected):
            return request.make_json_response(
                {"error": "unauthorized"}, status=401
            )
        snapshot = request.env["agenthub.relay.config"].sudo()._snapshot()
        return request.make_json_response(snapshot)
