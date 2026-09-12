import base64
import hashlib
import secrets
import time
from datetime import timedelta
from urllib.parse import quote, urlencode, urlparse

import requests

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


_GRAPH_ROOT = "https://graph.microsoft.com"
_OAUTH_CALLBACK = "/storage_backend_sharepoint/oauth/callback"
_TOKEN_TIMEOUT = 20
_GRAPH_TIMEOUT = 60


class SharePointTokenError(UserError):
    def __init__(self, message, error_code=None):
        super().__init__(message)
        self.error_code = error_code


class SharePointGraphService(models.AbstractModel):
    _name = "sharepoint.graph.service"
    _description = "Microsoft Graph Service for SharePoint Storage"

    @api.model
    def _credential(self, backend, user, create=False):
        backend.ensure_one()
        user.ensure_one()
        Credential = self.env["storage.sharepoint.credential"].sudo()
        credential = Credential.search(
            [("backend_id", "=", backend.id), ("user_id", "=", user.id)],
            limit=1,
        )
        if not credential and create:
            credential = Credential.create(
                {"backend_id": backend.id, "user_id": user.id}
            )
        return credential

    @api.model
    def _tenant_endpoint(self, backend, endpoint):
        tenant = quote(backend.sudo().sharepoint_tenant_id.strip(), safe="")
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/{endpoint}"

    @api.model
    def _redirect_uri(self):
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        ).rstrip("/")
        if not base_url:
            raise UserError(_("The web.base.url system parameter is not configured."))
        return f"{base_url}{_OAUTH_CALLBACK}"

    @api.model
    def _authorization_action(self, backend):
        backend.ensure_one()
        backend._sharepoint_validate_configuration()
        credential = self._credential(backend, self.env.user, create=True)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        state = secrets.token_urlsafe(32)
        credential.write(
            {
                "oauth_state": state,
                "oauth_state_expiry": fields.Datetime.now() + timedelta(minutes=10),
                "oauth_code_verifier": verifier,
            }
        )
        params = {
            "client_id": backend.sudo().sharepoint_client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri(),
            "response_mode": "query",
            "scope": backend.sudo().sharepoint_scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return {
            "type": "ir.actions.act_url",
            "url": f"{self._tenant_endpoint(backend, 'authorize')}?{urlencode(params)}",
            "target": "self",
        }

    @api.model
    def _token_request(self, backend, data):
        backend_sudo = backend.sudo()
        payload = {
            "client_id": backend_sudo.sharepoint_client_id,
            **data,
        }
        if backend_sudo.sharepoint_client_secret:
            payload["client_secret"] = backend_sudo.sharepoint_client_secret
        try:
            response = requests.post(
                self._tenant_endpoint(backend, "token"),
                data=payload,
                timeout=_TOKEN_TIMEOUT,
            )
        except requests.RequestException as error:
            raise UserError(_("Microsoft token endpoint is unavailable.")) from error
        if not response.ok:
            try:
                error_code = response.json().get("error", "token_error")
            except ValueError:
                error_code = "token_error"
            raise SharePointTokenError(
                _("Microsoft token request failed: %s", error_code),
                error_code=error_code,
            )
        return response.json()

    @api.model
    def _graph_me(self, access_token):
        try:
            response = requests.get(
                f"{_GRAPH_ROOT}/v1.0/me",
                params={"$select": "id,displayName,userPrincipalName"},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=_TOKEN_TIMEOUT,
            )
        except requests.RequestException as error:
            raise UserError(_("Microsoft Graph is unavailable.")) from error
        if response.status_code == 403:
            raise AccessError(_("The delegated token cannot read the current user."))
        if not response.ok:
            raise UserError(_("Microsoft Graph rejected the delegated token."))
        return response.json()

    @api.model
    def _store_user_tokens(self, backend, user, token_data, entra_oid=None):
        backend.ensure_one()
        user.ensure_one()
        access_token = token_data.get("access_token")
        if not access_token:
            raise UserError(_("Microsoft did not return an access token."))
        entra_oid = entra_oid or self._graph_me(access_token).get("id")
        if not entra_oid:
            raise UserError(_("Microsoft Graph did not return an Entra object ID."))
        credential = self._credential(backend, user, create=True)
        if credential.entra_oid and credential.entra_oid != entra_oid:
            raise AccessError(
                _("This Odoo user is already bound to another Entra identity.")
            )
        try:
            ttl = int(token_data.get("expires_in") or 0)
        except (TypeError, ValueError):
            ttl = 0
        values = {
            "entra_oid": entra_oid,
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token")
            or credential.refresh_token,
            "token_expiry": fields.Datetime.now() + timedelta(seconds=ttl)
            if ttl
            else False,
            "granted_scope": token_data.get("scope") or credential.granted_scope,
            "oauth_state": False,
            "oauth_state_expiry": False,
            "oauth_code_verifier": False,
        }
        credential.sudo().write(values)
        return credential

    @api.model
    def _complete_authorization(self, state, code, user):
        Credential = self.env["storage.sharepoint.credential"].sudo()
        credential = Credential.search(
            [("oauth_state", "=", state), ("user_id", "=", user.id)], limit=1
        )
        if not credential:
            raise AccessError(_("The SharePoint authorization state is invalid."))
        if (
            not credential.oauth_state_expiry
            or credential.oauth_state_expiry < fields.Datetime.now()
        ):
            credential.write(
                {
                    "oauth_state": False,
                    "oauth_state_expiry": False,
                    "oauth_code_verifier": False,
                }
            )
            raise AccessError(_("The SharePoint authorization state has expired."))
        backend = credential.backend_id
        backend._sharepoint_validate_configuration()
        token_data = self._token_request(
            backend,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri(),
                "scope": backend.sudo().sharepoint_scope,
                "code_verifier": credential.oauth_code_verifier,
            },
        )
        self._store_user_tokens(backend, user, token_data)
        return backend

    @api.model
    def _refresh_access_token(self, backend, user):
        credential = self._credential(backend, user)
        if not credential or not credential.refresh_token:
            raise AccessError(
                _("Your SharePoint authorization is missing or has expired.")
            )
        try:
            token_data = self._token_request(
                backend,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": credential.refresh_token,
                    "scope": backend.sudo().sharepoint_scope,
                },
            )
        except SharePointTokenError as error:
            if error.error_code == "invalid_grant":
                credential.write(
                    {
                        "access_token": False,
                        "refresh_token": False,
                        "token_expiry": False,
                    }
                )
            raise
        self._store_user_tokens(
            backend, user, token_data, entra_oid=credential.entra_oid
        )
        return credential.access_token

    @api.model
    def _get_access_token(self, backend, user=None, force_refresh=False):
        backend.ensure_one()
        user = user or self.env.user
        user.ensure_one()
        credential = self._credential(backend, user)
        if not credential:
            raise AccessError(
                _(
                    "Connect your Microsoft account to use SharePoint: "
                    "/storage_backend_sharepoint/connect/%s",
                    backend.id,
                )
            )
        valid_until = fields.Datetime.now() + timedelta(minutes=2)
        if (
            not force_refresh
            and credential.access_token
            and credential.token_expiry
            and credential.token_expiry >= valid_until
        ):
            return credential.access_token
        return self._refresh_access_token(backend, user)

    @api.model
    def _disconnect(self, backend, user):
        credential = self._credential(backend, user)
        if credential:
            credential.unlink()
        return True

    @api.model
    def _error_message(self, response):
        try:
            payload = response.json()
        except ValueError:
            return response.reason or _("Microsoft Graph request failed")
        error = payload.get("error", {})
        if isinstance(error, dict):
            return error.get("message") or error.get("code") or response.reason
        return str(error) or response.reason

    @api.model
    def _request(
        self,
        backend,
        method,
        path,
        *,
        user=None,
        params=None,
        json=None,
        data=None,
        headers=None,
        stream=False,
        timeout=_GRAPH_TIMEOUT,
    ):
        backend.ensure_one()
        user = user or self.env.user
        if path.startswith("http"):
            parsed = urlparse(path)
            if parsed.scheme != "https" or parsed.hostname != "graph.microsoft.com":
                raise AccessError(_("Microsoft Graph returned an unsafe continuation URL."))
            url = path
        else:
            url = f"{_GRAPH_ROOT}{path}"

        force_refresh = False
        for attempt in range(2):
            token = self._get_access_token(
                backend, user, force_refresh=force_refresh
            )
            request_headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                **(headers or {}),
            }
            try:
                response = requests.request(
                    method.upper(),
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=request_headers,
                    stream=stream,
                    timeout=timeout,
                )
            except requests.RequestException as error:
                raise UserError(_("Microsoft Graph is unavailable.")) from error

            if response.status_code == 401 and attempt == 0:
                response.close()
                force_refresh = True
                continue
            if response.status_code == 429 and attempt == 0:
                try:
                    delay = min(float(response.headers.get("Retry-After", "1")), 3.0)
                except ValueError:
                    delay = 1.0
                response.close()
                time.sleep(delay)
                continue
            if response.status_code == 404:
                response.close()
                raise FileNotFoundError(path)
            if response.status_code == 403:
                response.close()
                raise AccessError(_("SharePoint denied access to this item."))
            if not response.ok:
                message = self._error_message(response)
                status = response.status_code
                response.close()
                raise UserError(
                    _("Microsoft Graph request failed (%(status)s): %(message)s", status=status, message=message)
                )
            if stream:
                return response
            if response.status_code == 204 or not response.content:
                response.close()
                return {}
            try:
                payload = response.json()
            finally:
                response.close()
            return payload
        raise AccessError(_("Microsoft Graph request failed after retry."))
