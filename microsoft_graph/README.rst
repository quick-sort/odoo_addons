Microsoft Graph
===============

Shared Microsoft Graph authentication core for Odoo 19. It models an Entra
application registration, runs the delegated OAuth v2 authorization-code flow
(with PKCE) per Odoo user, keeps per-user tokens refreshed, and provides a
hardened Microsoft Graph HTTP client.

Storage or messaging addons that speak Microsoft Graph build on this module:
``storage_backend_sharepoint`` is the first consumer (SharePoint document
libraries). This module has no functionality of its own beyond the
authorization UI.

Application configuration
-------------------------

Create an **Microsoft Graph > Applications** record and configure:

* Entra tenant ID or verified tenant domain;
* Entra application/client ID;
* client secret (prefer ``server_environment``);
* delegated OAuth scopes shared by every consumer of the application.

The default scopes are read-only::

    offline_access openid profile Files.Read.All Sites.Read.All

Grant the corresponding delegated ``ReadWrite`` scopes in Entra only when a
consumer of this application needs to write. Never use application/client-
credentials permissions for per-user access: every request runs with the
delegated credential of the current Odoo user, so Microsoft applies the same
permissions the user has natively.

All these fields can be provided through ``server_environment`` (sections
``[microsoft_graph_application.<name>]`` or the global
``[microsoft_graph_application]`` section), like any ``server.env.mixin``
model.

The OAuth redirect URI is::

    https://<odoo-host>/microsoft_graph/oauth/callback

Register this exact Web redirect URI in the Entra application.

User authorization
------------------

The application form has **Connect Microsoft Account**. Because the user
already has an Entra browser session, authorization normally reuses SSO
without another password prompt. The callback uses authorization code with
PKCE, binds the returned Graph identity to the current Odoo user and stores a
per-user refresh token. A single consent covers every consumer of the
application: one credential is stored per (application, user).

Signed-in Odoo users can also start the flow themselves::

    /microsoft_graph/connect/<application_id>

Administrators can disable that self-service route with **Allow User
Authorization**.

An existing Entra SSO addon can persist the tokens obtained during login
instead of using the button::

    request.env.user._set_microsoft_graph_tokens(
        application,
        access_token=token_response["access_token"],
        refresh_token=token_response.get("refresh_token"),
        expires_in=token_response.get("expires_in"),
        scope=token_response.get("scope"),
        entra_oid=graph_user_id,
    )

The access token must have Microsoft Graph as its audience and contain
delegated permissions. A login-only ID token cannot be used.

Extension API for consumer addons
---------------------------------

Consumer addons depend on this module and use::

    self.env["microsoft.graph.service"]._request(
        application, method, "/v1.0/...", user=None, ...
    )

The service resolves the current user's (or ``user``'s) credential, attaches
the bearer token, refreshes it on 401, retries once on 429 honoring
``Retry-After``, maps 404 to ``FileNotFoundError`` and 403 to ``AccessError``
and parses Graph error payloads into ``UserError``. Continuation URLs are only
followed on ``https`` to ``graph.microsoft.com``.

Consumer addons reference an application record with a Many2one field and
should call ``application._graph_validate_configuration()`` before use.

Security notes
--------------

* Tokens are never stored on the application and are not returned through
  normal ORM field access. They are stored in the Odoo database like Odoo's
  built-in Microsoft credentials, so database encryption, backup protection
  and restricted database administration remain required.
* The OAuth state is single-use and expires after 10 minutes.
* ``offline_access`` in the scope set is what yields a refresh token.
