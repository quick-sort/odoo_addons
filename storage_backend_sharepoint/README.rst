Storage Backend SharePoint
==========================

Odoo 19 ``storage.backend`` provider for SharePoint document libraries, built
on the shared ``microsoft_graph`` authentication core. It does not depend on
``one_storage`` and does not replace ``ir.attachment``.

Every Graph request uses the delegated credential of the current Odoo user
(see ``microsoft_graph``). Microsoft Graph and SharePoint therefore apply the
same permissions as the user has in SharePoint itself.

Backend configuration
---------------------

First configure a **Microsoft Graph > Applications** record (tenant, client
ID, secret, delegated scopes). The scopes must cover what this backend needs:
the read-only default ``Files.Read.All Sites.Read.All`` works for read-only
backends; grant the corresponding delegated ``ReadWrite`` scopes in Entra for
writable backends. Never use application/client-credentials permissions for
per-user access.

Then create a storage backend with type **Microsoft SharePoint** and
configure:

* the Microsoft Graph application;
* SharePoint document library Graph drive ID;
* optional root driveItem ID;
* optional ``directory_path`` below that root.

One Entra application can back several backends; users authorize once per
application and every backend on it reuses that credential. Applications that
must stay read-only should use a separate application record with read-only
scopes, or rely on the backend-level **Read Only** flag, which blocks uploads,
renames, moves and deletions in Odoo.

The OAuth redirect URI (register it in the Entra application) is the one of
``microsoft_graph``::

    https://<odoo-host>/microsoft_graph/oauth/callback

User authorization
------------------

Users click **Connect Microsoft Account** — either on the application form
(``microsoft_graph``) or on the backend form. Because the user already has an
Entra browser session, authorization normally reuses SSO without another
password prompt. The callback binds the returned Graph identity to the
current Odoo user and stores a per-user refresh token.

A storage consumer can start the same flow for a normal internal user by
redirecting to::

    /storage_backend_sharepoint/connect/<backend_id>

Administrators can disable that self-service route per application with the
application's **Allow User Authorization** flag.

An existing Entra SSO addon can persist the tokens obtained during login
instead of using the button — see the ``microsoft_graph`` README for the
``_set_microsoft_graph_tokens`` hook.

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

* Tokens live on ``microsoft.graph.credential`` and are never returned through
  normal ORM field access (see ``microsoft_graph`` security notes).
* The adapter always resolves credentials from the active Odoo user; callers
  must use ``with_user(original_user)`` for background jobs.
* A backend maps one document library and optional root. Configure multiple
  backends for multiple libraries.
* Graph HTTP 403 remains an Odoo access error. HTTP 404 is treated as missing
  because SharePoint may conceal unauthorized items as not found.
* Temporary download and upload URLs are never persisted or logged.

Upgrade notes
-------------

Version 19.0.2.0.0 splits authentication into the ``microsoft_graph`` addon.
The ``sharepoint_tenant_id`` / ``sharepoint_client_id`` /
``sharepoint_client_secret`` / ``sharepoint_scope`` backend fields and the
``storage.sharepoint.credential`` model are gone: create a
``microsoft.graph.application`` from the former values, point the backend at
it, and let users re-connect once.
