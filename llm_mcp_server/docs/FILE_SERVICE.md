# MCP File Service (`attachment_*`)

The MCP server ships a file upload/download capability backed by
`ir.attachment`. It is independent of `storage_backend`: the attachment decides
where its bytes live (DB, filestore, or an external storage implementation).

## Tools

| Tool | Purpose |
| --- | --- |
| `attachment_stage_upload(filename)` | Create an unbound empty attachment and return `attachment_id` plus a temporary upload URL |
| `attachment_commit_upload(attachment_id, res_model="", res_id=0)` | Verify the uploaded bytes and optionally bind the attachment to a business record |
| `attachment_get_download_url(attachment_id)` | Return a short-lived `/web/content` URL |

`attachment_id` is an `ir.attachment` id and the only cross-tool reference. No
backend names, paths or listing tools are exposed.

## Upload flow

1. `attachment_stage_upload` creates an **unbound** attachment (`name` only) and a
   `llm.mcp.file.upload` staging row (`pending`, 24 h TTL). Until commit the
   attachment is visible only to its creator and administrators (core
   `_check_access`).
2. The tool signs an upload URL with
   `odoo.tools.misc.limited_field_access_token(attachment, "raw", scope="llm_attachment_upload")`.
   The token is bound to the attachment id and expires after 1 hour.
3. `PUT /mcp/files/<attachment_id>?access_token=...` verifies the signature,
   claims the staging row atomically (`pending` → `uploaded`), writes the body
   with `attachment.write({"raw": data})` and records `sha256`/size.
4. `attachment_commit_upload` requires `uploaded`, optionally binds
   `res_model`/`res_id` **as the caller** (core checks write access to that
   record), and moves the staging row to `committed`.

Zero-byte files are accepted when the client sends an explicit
`Content-Length: 0`. Multipart bodies are rejected (415): the body must be the
raw file (`curl -T <file>`).

## Download flow

`attachment_get_download_url` first calls `attachment.check_access("read")` as the
caller, then signs a `/web/content/ir.attachment/<id>/raw` URL with
`limited_field_access_token(..., scope="binary")` (10 minutes). Serving is done
by Odoo's native `/web/content` controller, so streaming/Range and access-token
validation are core behaviour; there is no custom download relay.

## Access model

- Bound attachment: access follows the `res_model`/`res_id` record's ACL and
  record rules.
- Unbound attachment: only the creator and administrators can read it.
- `public` is never set and `res_field` is never used.
- Upload and download tokens use different scopes, so a download token cannot
  be replayed against the upload endpoint, and vice versa.

## Cleanup

`llm.mcp.file.upload._cron_gc()` runs hourly. It deletes stale `pending` or
`uploaded` staging rows together with their uncommitted attachments; committed
attachments are never deleted, and their staging rows are pruned after 30 days.

## Configuration

`llm_mcp_server.max_file_upload_mb` (default 64) caps the relay upload size.
