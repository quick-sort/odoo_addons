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
        entry = request.env["one.storage.entry"].browse(entry_id).exists()
        if not entry or entry.is_dir:
            raise request.not_found()
        headers = [
            ("Content-Type", entry.mimetype or "application/octet-stream"),
            ("Content-Disposition", 'attachment; filename="%s"' % entry.name),
        ]
        return request.make_response(entry.iter_chunks(), headers=headers)

    @http.route(
        "/one_storage/entry/<int:entry_id>/preview",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def preview_node(self, entry_id, **kw):
        entry = request.env["one.storage.entry"].browse(entry_id).exists()
        if not entry or entry.is_dir:
            raise request.not_found()
        headers = [
            ("Content-Type", entry.mimetype or "application/octet-stream"),
            ("Content-Disposition", "inline"),
        ]
        return request.make_response(entry.iter_chunks(), headers=headers)
