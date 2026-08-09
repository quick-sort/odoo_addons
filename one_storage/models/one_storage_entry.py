# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Unified inode-like entry model.

A single ``one.storage.entry`` represents either a directory (``is_dir``) or
a file inside the virtual folder tree, mirroring a real filesystem inode:
directories nest via ``parent_id`` and may carry mount points; files carry
bytes metadata and resolve their storage through the parent chain.
"""

import hashlib
import logging
import mimetypes
import posixpath

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


def _join_backend_path(base, *segments):
    """Join ``base`` (a backend root path) with ``segments`` (folder names).

    Returns ``base`` when there are no segments, otherwise
    ``posixpath.join(base or "", *segments)``.
    """
    if not segments:
        return base or ""
    return posixpath.join(base or "", *segments)


class OneStorageEntry(models.Model):
    """A directory, file or symlink in the virtual folder tree."""

    _name = "one.storage.entry"
    _description = "One Storage Entry"
    _order = "parent_path"
    _parent_name = "parent_id"
    _parent_store = True

    name = fields.Char(required=True)
    entry_type = fields.Selection(
        selection=[
            ("directory", "Directory"),
            ("file", "File")
        ],
        required=True,
        default="file",
    )
    is_dir = fields.Boolean(
        compute="_compute_is_dir",
        store=True,
        help="True for directories. Kept as a convenience flag so existing "
        "domain/filters and the UI can branch on 'is this a folder'.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
    )

    parent_id = fields.Many2one(
        comodel_name="one.storage.entry",
        ondelete="restrict",
        index=True,
    )
    child_ids = fields.One2many(
        comodel_name="one.storage.entry",
        inverse_name="parent_id",
        string="Children",
    )
    parent_path = fields.Char(index=True)
    complete_name = fields.Char(
        compute="_compute_complete_name",
        store=True,
        recursive=True,
    )

    # Directories: explicit backend binding for the subtree (optional).
    # Files: denormalized, computed from the parent chain.
    backend_id = fields.Many2one(
        comodel_name="storage.backend",
        compute="_compute_backend_info",
        store=True,
        readonly=False,
        help="Storage backend for this entry. On a directory this binds the "
        "whole subtree; on a file it is resolved from the parent chain.",
    )
    backend_path = fields.Char(
        compute="_compute_backend_info",
        store=True,
        readonly=False,
        help="Path of this entry inside its backend. On a directory this is "
        "the root path for its own files; on a file it is resolved.",
    )

    # File-only metadata
    mimetype = fields.Char()
    file_size = fields.Integer()
    checksum = fields.Char(size=40)
    url = fields.Char()
    state = fields.Selection(
        selection=[("draft", "Draft"), ("synced", "Synced"), ("error", "Error")],
        default="draft",
    )
    last_sync = fields.Datetime()

    # Directory-only: mount points graft another backend onto this subtree.
    mount_ids = fields.One2many(
        comodel_name="one.storage.mount",
        inverse_name="entry_id",
    )

    # Symlink-only: the entry this link points to (within the same tree).
    target_id = fields.Many2one(
        comodel_name="one.storage.entry",
        help="Target entry for symlinks. Resolving the link transparently "
        "follows this reference, like a POSIX symlink.",
    )

    _parent_name_uniq = models.Constraint(
        "unique(parent_id, name)",
        "An entry with this name already exists here.",
    )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    @api.depends("entry_type")
    def _compute_is_dir(self):
        for entry in self:
            entry.is_dir = entry.entry_type == "directory"

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for entry in self:
            if entry.parent_id:
                entry.complete_name = posixpath.join(
                    entry.parent_id.complete_name or "", entry.name
                )
            else:
                entry.complete_name = "/" + entry.name if entry.name else "/"

    @api.constrains("parent_id", "name")
    def _check_name_unique_in_parent(self):
        for entry in self:
            domain = [("name", "=", entry.name)]
            if entry.parent_id:
                domain.append(("parent_id", "=", entry.parent_id.id))
            else:
                domain.append(("parent_id", "=", False))
            clash = self.search(domain + [("id", "!=", entry.id)], limit=1)
            if clash:
                raise ValidationError(
                    _("An entry named '%s' already exists here.", entry.name)
                )

    @api.constrains("parent_id", "company_id")
    def _check_single_root_per_company(self):
        """Each company has at most one root entry (parent_id is null)."""
        for entry in self:
            if entry.parent_id:
                continue
            clash = self.search(
                [
                    ("parent_id", "=", False),
                    ("company_id", "=", entry.company_id.id),
                    ("id", "!=", entry.id),
                ],
                limit=1,
            )
            if clash:
                raise ValidationError(
                    _("Company %s already has a root folder."),
                    entry.company_id.display_name,
                )

    @api.constrains("parent_id")
    def _check_parent_recursion(self):
        if not self._check_recursion(parent="parent_id"):
            raise ValidationError(_("Folder hierarchy must not contain cycles."))

    # ------------------------------------------------------------------
    # Backend resolution
    # ------------------------------------------------------------------
    def _resolve_backend(self):
        """Return ``(backend, relative_path)`` for a directory.

        Walk up the tree looking for the closest mount point first; if none
        applies, fall back to the closest directory carrying a ``backend_id``.
        ``relative_path`` is the directory's path inside the resolved backend.

        Uses ``parent_path`` so the whole ancestor chain is read in one shot
        instead of one query per level.
        """
        self.ensure_one()
        if not self.is_dir:
            return self.parent_id._resolve_backend()
        ids = [int(x) for x in (self.parent_path or "").split("/") if x]
        chain = self.browse(ids)
        by_id = {node.id: node for node in chain}
        segments = []
        for node in (by_id[i] for i in reversed(ids)):
            mount = node.mount_ids.filtered("active")[:1]
            if mount:
                return mount.backend_id, _join_backend_path(
                    mount.backend_path, *reversed(segments)
                )
            if node.backend_id:
                return node.backend_id, _join_backend_path(
                    node.backend_path, *reversed(segments)
                )
            segments.append(node.name)
        raise ValidationError(
            _("Folder '%s' is not bound to any storage backend.", self.complete_name)
        )

    @api.depends("entry_type", "name", "parent_id", "parent_id.mount_ids")
    def _compute_backend_info(self):
        for entry in self:
            if entry.is_dir:
                # Directories keep their explicit backend binding; only files
                # are resolved from the parent chain.
                continue
            if not entry.parent_id:
                continue
            backend, rel_path = entry.parent_id._resolve_backend()
            entry.backend_id = backend
            entry.backend_path = (
                posixpath.join(rel_path, entry.name) if rel_path else entry.name
            )

    @api.onchange("name", "parent_id", "entry_type")
    def _onchange_backend_info(self):
        for entry in self:
            if entry.is_dir or not entry.parent_id:
                continue
            backend, rel_path = entry.parent_id._resolve_backend()
            entry.backend_id = backend
            entry.backend_path = (
                posixpath.join(rel_path, entry.name) if rel_path else entry.name
            )

    def _follow(self):
        """Resolve symlinks, returning the real entry behind a link.

        Non-symlink entries return themselves. Guarded against cycles so a
        link pointing (directly or transitively) to itself returns the link
        rather than looping forever.
        """
        self.ensure_one()
        seen = set()
        current = self
        while current.entry_type == "symlink" and current.target_id:
            if current.id in seen:
                break
            seen.add(current.id)
            current = current.target_id
        return current

    def resolve_path(self, segments):
        """Walk ``segments`` down the tree from this entry.

        Returns the deepest ``one.storage.entry`` reached. Symlinks are
        followed transparently (POSIX semantics). An intermediate segment
        that names a file (rather than a directory) raises ``ValueError``;
        so does an unknown name.
        """
        current = self._follow()
        for index, segment in enumerate(segments):
            child = self.search(
                [("parent_id", "=", current.id), ("name", "=", segment)], limit=1
            )
            if not child:
                raise ValueError(_("'%s' not found.", segment))
            child = child._follow()
            if not child.is_dir and index != len(segments) - 1:
                raise ValueError(_("'%s' is a file, not a folder.", segment))
            current = child
        return current

    def list_children(self):
        """Return the mixed child entries (dirs and files) under this folder."""
        return self.search([("parent_id", "=", self.id)], order="sequence, name")

    @api.model
    def _get_or_create_root(self, company=None):
        """Return the single root folder for ``company``.

        Creates a default local-filesystem backend bound to the company and
        the root entry if they do not yet exist. Idempotent.
        """
        company = company or self.env.company
        root = self.search(
            [("parent_id", "=", False), ("company_id", "=", company.id)], limit=1
        )
        if root:
            return root
        backend = self.env["storage.backend"].create(
            {
                "name": _("%s storage") % company.name,
                "backend_type": "filesystem",
                "directory_path": "company_%s" % company.id,
            }
        )
        return self.create(
            {
                "name": company.name,
                "entry_type": "directory",
                "company_id": company.id,
                "backend_id": backend.id,
            }
        )

    def action_open_children(self):
        """Card click handler for the file browser.

        Directories descend one level (breadcrumb-able); files open their
        form view. Symlinks are followed to their target first. Used as
        ``<kanban action="action_open_children" type="object">`` so the whole
        card is clickable.
        """
        self.ensure_one()
        target = self._follow()
        if not target.is_dir:
            return {
                "type": "ir.actions.act_window",
                "name": self.name,
                "res_model": "one.storage.entry",
                "view_mode": "form",
                "res_id": self.id,
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "one.storage.entry",
            "view_mode": "kanban,list,form",
            "domain": [("parent_id", "=", target.id)],
            "context": {
                "default_parent_id": target.id,
                "default_entry_type": "file",
            },
            "target": "current",
        }

    # ------------------------------------------------------------------
    # Sync from backend (async batch)
    # ------------------------------------------------------------------
    def action_sync_from_backend(self):
        """Enqueue a job that materializes backend entries as file entries."""
        for entry in self:
            if not entry.is_dir:
                continue
            entry.with_delay(
                channel="root.one_storage",
                description=_("Sync folder %s") % entry.complete_name,
            )._sync_from_backend()

    def _sync_from_backend(self):
        """Create/update file entries from the backend's actual content."""
        self.ensure_one()
        if not self.is_dir:
            return
        backend, rel_path = self._resolve_backend()
        try:
            entries = backend.list_files(rel_path, detail=True)
        except Exception as err:  # noqa: BLE001
            _logger.warning("Sync failed for %s: %s", self.complete_name, err)
            return
        existing = {n.name: n for n in self.child_ids}
        for entry_name, size in entries:
            if entry_name in existing:
                continue
            if backend.list_files(posixpath.join(rel_path, entry_name)):
                # has children => a directory, materialized through the tree
                continue
            self.env["one.storage.entry"].create(
                {
                    "name": entry_name,
                    "entry_type": "file",
                    "parent_id": self.id,
                    "file_size": size or 0,
                    "mimetype": mimetypes.guess_type(entry_name)[0],
                }
            )

    # ------------------------------------------------------------------
    # CRUD hooks: keep the backend in sync with file entry lifecycle
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        entries = super().create(vals_list)
        for entry in entries:
            if not entry.is_dir and entry._needs_upload():
                entry._refresh_metadata()
        return entries

    def write(self, vals):
        res = super().write(vals)
        if "parent_id" in vals or "name" in vals or "entry_type" in vals:
            for entry in self:
                if not entry.is_dir:
                    entry._refresh_metadata()
        return res

    def unlink(self):
        for entry in self:
            if entry.is_dir:
                if entry.child_ids:
                    raise ValidationError(
                        _("Folder '%s' is not empty.", entry.name)
                    )
            else:
                try:
                    entry.backend_id.delete(entry.backend_path)
                except Exception as err:  # noqa: BLE001
                    _logger.warning(
                        "Could not delete %s on backend: %s", entry.backend_path, err
                    )
        return super().unlink()

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------
    def _needs_upload(self):
        """Hook for callers that push bytes via create."""
        return False

    def _refresh_metadata(self):
        for entry in self:
            if entry.is_dir or not (entry.backend_id and entry.backend_path):
                continue
            try:
                if not entry.backend_id.exists(entry.backend_path):
                    entry.state = "draft"
                    continue
                size = entry.backend_id.get_size(entry.backend_path)
            except Exception:  # noqa: BLE001
                entry.state = "draft"
                continue
            entry.write(
                {
                    "file_size": size,
                    "mimetype": entry.mimetype or mimetypes.guess_type(entry.name)[0],
                    "state": "synced",
                    "last_sync": fields.Datetime.now(),
                }
            )

    def set_content(self, data, binary=True):
        """Push raw bytes to the backend and refresh metadata.

        Large uploads should go through the async batch operation model
        rather than this synchronous path.
        """
        for entry in self:
            if entry.is_dir or not entry.backend_id:
                raise ValidationError(
                    _("Entry %s has no backend to write to.", entry.display_name)
                )
            entry.backend_id.add(entry.backend_path, data, binary=binary)
            if not binary:
                import base64

                raw = base64.b64decode(data)
            else:
                raw = data
            checksum = hashlib.sha1(raw).hexdigest()
            entry.write(
                {
                    "file_size": len(raw),
                    "mimetype": mimetypes.guess_type(entry.name)[0] or entry.mimetype,
                    "checksum": checksum,
                    "state": "synced",
                    "last_sync": fields.Datetime.now(),
                }
            )
        return True

    # ------------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------------
    def action_resync(self):
        self._refresh_metadata()

    def action_download(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/one_storage/entry/%s/download" % self.id,
            "target": "self",
        }

    # ------------------------------------------------------------------
    # Async batch operations (queue_job)
    # ------------------------------------------------------------------
    def action_batch_delete(self):
        for entry in self:
            if entry.is_dir:
                continue
            entry.with_delay(
                channel="root.one_storage",
                description=_("Delete %s") % entry.display_name,
            )._batch_delete()

    def _batch_delete(self):
        self.ensure_one()
        try:
            self.backend_id.delete(self.backend_path)
        except Exception as err:  # noqa: BLE001
            _logger.warning("Batch delete failed for %s: %s", self.backend_path, err)
        self.unlink()

    def action_batch_move(self, dest_entry):
        for entry in self:
            if entry.is_dir or not dest_entry.is_dir:
                continue
            entry.with_delay(
                channel="root.one_storage",
                description=_("Move %s") % entry.display_name,
            )._batch_move(dest_entry.id)

    def _batch_move(self, dest_entry_id):
        self.ensure_one()
        dest_entry = self.env["one.storage.entry"].browse(dest_entry_id)
        dest_backend, dest_rel = dest_entry._resolve_backend()
        dest_path = posixpath.join(dest_rel, self.name) if dest_rel else self.name
        data = self.backend_id.get(self.backend_path)
        dest_backend.add(dest_path, data)
        self.backend_id.delete(self.backend_path)
        self.write({"parent_id": dest_entry_id})
