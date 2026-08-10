# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import http
from odoo.http import request


class OneStorageController(http.Controller):
    @http.route(
        "/one_storage/entry/<int:entry_id>/download",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def download_node(self, entry_id, **kw):
        entry = request.env["one.storage.entry"].browse(entry_id)
        entry.ensure_one()
        if not entry.exists() or entry.is_dir:
            raise request.not_found()
        data = entry.backend_id.get(entry.backend_path)
        headers = [
            ("Content-Type", entry.mimetype or "application/octet-stream"),
            ("Content-Disposition", 'attachment; filename="%s"' % entry.name),
            ("Content-Length", str(len(data))),
        ]
        return request.make_response(data, headers=headers)

    @http.route(
        "/one_storage/entry/<int:entry_id>/preview",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def preview_node(self, entry_id, **kw):
        entry = request.env["one.storage.entry"].browse(entry_id)
        entry.ensure_one()
        if not entry.exists() or entry.is_dir:
            raise request.not_found()
        data = entry.backend_id.get(entry.backend_path)
        headers = [
            ("Content-Type", entry.mimetype or "application/octet-stream"),
            ("Content-Disposition", "inline"),
            ("Content-Length", str(len(data))),
        ]
        return request.make_response(data, headers=headers)
