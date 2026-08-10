# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Unified inode-like entry model.

A single ``one.storage.entry`` represents either a directory (``is_dir``) or
a file inside the virtual folder tree, mirroring a real filesystem inode:
directories nest via ``parent_id`` and may carry mount points; files carry
bytes metadata and resolve their storage through the parent chain.
"""

import errno
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

    @api.constrains("parent_id")
    def _check_single_root(self):
        """At most one root entry (parent_id is null) exists globally."""
        for entry in self:
            if entry.parent_id:
                continue
            clash = self.search(
                [("parent_id", "=", False), ("id", "!=", entry.id)], limit=1
            )
            if clash:
                raise ValidationError(_("A root folder already exists."))

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
    def _get_or_create_root(self):
        """Return the single global root folder.

        Bound to the default storage backend (see
        :meth:`storage.backend._get_or_create_default`). Idempotent.
        """
        root = self.search([("parent_id", "=", False)], limit=1)
        if root:
            return root
        backend = self.env["storage.backend"]._get_or_create_default()
        return self.create(
            {
                "name": "One Storage",
                "entry_type": "directory",
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
    def action_mount(self):
        """Open the wizard to mount a backend onto this directory."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Mount Backend"),
            "res_model": "one.storage.entry.mount.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_entry_id": self.id},
        }

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
        """Materialize backend entries as file/directory entries, recursively.

        Walks the whole subtree under ``self`` in the resolved backend and
        mirrors it: directories become ``directory`` entries (recursed into),
        files become ``file`` entries carrying ``file_size`` and ``mimetype``.
        Idempotent — existing entries are kept and only missing ones are added.
        """
        self.ensure_one()
        if not self.is_dir:
            return
        try:
            backend, rel_path = self._resolve_backend()
        except ValidationError as err:
            _logger.warning("Sync failed for %s: %s", self.complete_name, err)
            return
        self._sync_from_backend_path(backend, rel_path)

    def _sync_from_backend_path(self, backend, rel_path):
        """Sync one directory level of ``backend`` under ``self``.

        ``rel_path`` is this entry's path inside ``backend``. Each backend
        child is created as a file or directory entry; subdirectories are
        recursed into with their explicit path so we never re-resolve the
        parent chain.
        """
        self.ensure_one()
        try:
            entries = backend.list_files(rel_path, detail=True)
        except Exception as err:  # noqa: BLE001
            _logger.warning("Sync failed for %s: %s", self.complete_name, err)
            return
        existing = {child.name: child for child in self.child_ids}
        for entry_name, size in entries:
            child_path = posixpath.join(rel_path, entry_name) if rel_path else entry_name
            is_subdir = bool(backend.list_files(child_path))
            child = existing.get(entry_name)
            if child is None:
                child = self.env["one.storage.entry"].create(
                    {
                        "name": entry_name,
                        "entry_type": "directory" if is_subdir else "file",
                        "parent_id": self.id,
                        "file_size": size or 0,
                        "mimetype": mimetypes.guess_type(entry_name)[0],
                    }
                )
            if is_subdir:
                child._sync_from_backend_path(backend, child_path)

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
                if not entry.backend_id.file_exists(entry.backend_path):
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
    # Public file API (for external addons)
    #
    # Pathlib-style CRUD over the VFS tree. External addons navigate with
    # `_get_or_create_root()` / `resolve_path()` then operate on the returned
    # entry records. Failures raise Python OSError subclasses
    # (FileNotFoundError, IsADirectoryError, ...) so callers can handle them
    # like real filesystem errors. Note: existence is `file_exists()`, NOT
    # `exists()`, which is Odoo's recordset filter.
    # ------------------------------------------------------------------
    def read_bytes(self):
        """Return this file's raw bytes. Mirrors pathlib.Path.read_bytes."""
        self.ensure_one()
        if self.is_dir:
            raise IsADirectoryError(self.complete_name)
        return self.backend_id.get(self.backend_path)

    def write_bytes(self, data):
        """Write raw bytes to this file, creating or overwriting it."""
        self.ensure_one()
        if self.is_dir:
            raise IsADirectoryError(self.complete_name)
        self.set_content(data, binary=True)
        return self

    def mkdir(self, name, parents=False):
        """Create a child directory and return the new entry.

        With ``parents=True``, ``name`` may contain ``/`` and every missing
        level is created (existing directory levels are reused). Raises
        ``FileExistsError`` when a plain target already exists and
        ``NotADirectoryError`` when ``self`` is not a directory or an
        intermediate level names a file.
        """
        self.ensure_one()
        if not self.is_dir:
            raise NotADirectoryError(self.complete_name)
        if parents:
            current = self
            for segment in name.split("/"):
                current = current._mkdir_step(segment)
            return current
        return self._mkdir_step(name, exist_ok=False)

    def _mkdir_step(self, name, exist_ok=True):
        child = self.search(
            [("parent_id", "=", self.id), ("name", "=", name)], limit=1
        )
        if child:
            if not child.is_dir:
                raise NotADirectoryError(self.complete_name)
            if exist_ok:
                return child
            raise FileExistsError(self.complete_name)
        return self.create(
            {"name": name, "entry_type": "directory", "parent_id": self.id}
        )

    def create_file(self, name, data=None):
        """Create a file entry under this directory and return it.

        When ``data`` is given it is written to the backend immediately;
        otherwise the entry starts empty (``state='draft'``). Raises
        ``FileExistsError`` if ``name`` already exists here.
        """
        self.ensure_one()
        if not self.is_dir:
            raise NotADirectoryError(self.complete_name)
        if self.search(
            [("parent_id", "=", self.id), ("name", "=", name)], limit=1
        ):
            raise FileExistsError(self.complete_name)
        entry = self.create(
            {"name": name, "entry_type": "file", "parent_id": self.id}
        )
        if data is not None:
            entry.write_bytes(data)
        return entry

    def remove(self):
        """Delete this file and its backend bytes. Mirrors os.remove."""
        self.ensure_one()
        if self.is_dir:
            raise IsADirectoryError(self.complete_name)
        self.unlink()

    def rmdir(self):
        """Delete this directory; it must be empty. Mirrors os.rmdir."""
        self.ensure_one()
        if not self.is_dir:
            raise NotADirectoryError(self.complete_name)
        if self.child_ids:
            raise OSError(
                errno.ENOTEMPTY, "Directory not empty", self.complete_name
            )
        self.unlink()

    def stat(self):
        """Return metadata as a dict.

        For files, backend existence is validated (``FileNotFoundError``
        when the bytes are missing) and ``size`` is read live. Directories
        may be lazy (no backend counterpart until a file is written), so
        their stat is purely logical.
        """
        self.ensure_one()
        if self.is_dir:
            return {
                "is_dir": True,
                "size": None,
                "mimetype": self.mimetype,
                "checksum": self.checksum,
                "mtime": self.last_sync,
            }
        backend = self.backend_id
        if not backend or not backend.file_exists(self.backend_path):
            raise FileNotFoundError(self.complete_name)
        return {
            "is_dir": False,
            "size": backend.get_size(self.backend_path),
            "mimetype": self.mimetype,
            "checksum": self.checksum,
            "mtime": self.last_sync,
        }

    def file_exists(self):
        """Whether this entry's bytes exist on the backend.

        Directories always report True (logical existence); a file reports
        False while its backend bytes are absent (state 'draft').
        """
        self.ensure_one()
        if self.is_dir:
            return True
        if not self.backend_id:
            return False
        return self.backend_id.file_exists(self.backend_path)

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

    def action_edit(self):
        """Open the entry's form view."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "one.storage.entry",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }

    def action_delete(self):
        """Open the delete confirmation wizard."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Delete Entry"),
            "res_model": "one.storage.entry.delete.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_entry_id": self.id},
        }

    def action_upload(self):
        """Open the upload wizard to overwrite this file's content."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Upload"),
            "res_model": "one.storage.entry.upload.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_entry_id": self.id},
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
