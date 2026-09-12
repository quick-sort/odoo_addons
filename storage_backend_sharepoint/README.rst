Storage Backend SharePoint
==========================

Odoo 19 ``storage.backend`` provider for SharePoint document libraries. It
does not depend on ``one_storage`` and does not replace ``ir.attachment``.

Every Graph request uses the delegated credential of the current Odoo user.
Microsoft Graph and SharePoint therefore apply the same permissions as the
user has in SharePoint itself.

Backend configuration
---------------------

Create a storage backend with type **Microsoft SharePoint** and configure:

* Entra tenant ID or verified tenant domain;
* Entra application/client ID;
* client secret (prefer ``server_environment``);
* delegated OAuth scopes;
* SharePoint document library Graph drive ID;
* optional root driveItem ID;
* optional ``directory_path`` below that root.

The default scopes are read-only::

    offline_access openid profile Files.Read.All Sites.Read.All

For a writable backend, disable **Read Only** and grant the corresponding
delegated ``ReadWrite`` scopes in Entra. Never use application/client-
credentials permissions for per-user access.

The OAuth redirect URI is::

    https://<odoo-host>/storage_backend_sharepoint/oauth/callback

Register this exact Web redirect URI in the Entra application.

User authorization
------------------

The backend form has **Connect Microsoft Account**. Because the user already
has an Entra browser session, authorization normally reuses SSO without
another password prompt. The callback uses authorization code with PKCE,
binds the returned Graph identity to the current Odoo user, and stores a
per-user refresh token. A storage consumer can start the same flow for a
normal internal user by redirecting to::

    /storage_backend_sharepoint/connect/<backend_id>

Administrators can disable that self-service route per backend with **Allow
User Authorization**.

An existing Entra SSO addon can persist the tokens obtained during login
instead of using the button::

    request.env.user._set_sharepoint_auth_tokens(
        backend,
        access_token=token_response["access_token"],
        refresh_token=token_response.get("refresh_token"),
        expires_in=token_response.get("expires_in"),
        scope=token_response.get("scope"),
        entra_oid=graph_user_id,
    )

The access token must have Microsoft Graph as its audience and contain
delegated SharePoint/Files permissions. A login-only ID token cannot be used.

Storage API
-----------

The adapter implements:

* ``open(path, "rb" | "wb")``;
* ``list_files()`` and recursive listing through the base adapter;
* ``file_exists()``, ``stat()``, ``get_size()``;
* ``rename()``, ``move_files()``;
* ``delete()``, ``rmdir()``;
* ``action_test_config()``.

Small uploads use the Graph content endpoint. Larger uploads use a resumable
upload session with sequential chunks.

Security notes
--------------

* Tokens are never stored on ``storage.backend`` and are not returned through
  normal ORM field access. They are stored in the Odoo database like Odoo's
  built-in Microsoft credentials, so database encryption, backup protection
  and restricted database administration remain required.
* The adapter always resolves credentials from the active Odoo user; callers
  must use ``with_user(original_user)`` for background jobs.
* A backend maps one document library and optional root. Configure multiple
  backends for multiple libraries.
* Graph HTTP 403 remains an Odoo access error. HTTP 404 is treated as missing
  because SharePoint may conceal unauthorized items as not found.
* Temporary download and upload URLs are never persisted or logged.
