# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Unified inode-like entry model.

A single ``one.storage.entry`` represents either a directory (``is_dir``) or
a file inside the virtual folder tree, mirroring a real filesystem inode.

A directory that carries a ``backend_id`` is the **root of a backend mirror**:
its subtree mirrors that ``storage.backend`` (root ``/``). Files created under
it are stored in that backend; their relative path is derived on demand from
their logical path under the mirror root.

**Bind mounts**: any directory whose ``target_id`` points at a backend root
entry becomes an alias for that mirror — listing, reading and writing it
transparently operates on the mirror tree. One backend root can be the target
of many directories, so the same backend can appear at several paths.
``_follow`` resolves a bind (or symlink) to the real entry behind it.
"""

import base64
import errno
import hashlib
import logging
import mimetypes
import posixpath
import shutil

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


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

    # Directories carrying a backend_id are the root of a backend mirror.
    # Files resolve their backend by walking up to the nearest such directory.
    backend_id = fields.Many2one(
        comodel_name="storage.backend",
        help="Storage backend mirrored by this directory's subtree. Set on a "
        "directory to mark it as a backend mirror root.",
    )
    # Read/write policy for the mirror. Lives on the backend root entry so one
    # backend has one policy across every path it is bound to.
    read_only = fields.Boolean(
        default=False,
        help="When set on a backend mirror root, the whole mirror is "
        "read-only: writes, deletes and creation are rejected.",
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

    # A directory whose ``target_id`` points at a backend root entry becomes a
    # bind mount for that mirror (an alias). Also covers plain symlinks.
    target_id = fields.Many2one(
        comodel_name="one.storage.entry",
        help="Target entry this one aliases. For a directory pointing at a "
        "backend mirror root, this is a bind mount: operating on this entry "
        "transparently operates on the mirror tree. One target may be aliased "
        "by many entries, so a backend can appear at several paths.",
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

    @api.constrains("parent_id", "name")
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
    def _resolve_chain(self):
        """Return the ancestor chain (root-first) read in one query.

        ``parent_path`` is ``"root_id/.../self_id"``; we read every node once
        and return them ordered from the top of the tree down to ``self``.
        """
        self.ensure_one()
        ids = [int(x) for x in (self.parent_path or "").split("/") if x]
        chain = {node.id: node for node in self.browse(ids)}
        return [chain[i] for i in ids]

    def _resolve_backend(self):
        """Return ``(backend, mirror_root)`` for this entry.

        Walks up the ancestor chain to the nearest node carrying a
        ``backend_id`` (a backend mirror root). ``mirror_root`` is that node.
        """
        self.ensure_one()
        for node in reversed(self._resolve_chain()):
            if node.backend_id:
                return node.backend_id, node
        raise ValidationError(
            _("Entry '%s' is not under a storage backend mirror.", self.complete_name)
        )

    def _backend_relpath(self):
        """Path of this entry inside its backend, relative to the mirror root.

        The mirror root maps to ``""``; a direct child ``x`` maps to ``x``;
        nested directories join with ``/``. Computed from the logical parent
        chain, never stored.
        """
        self.ensure_one()
        chain = self._resolve_chain()
        # Walk from the leaf up; stop after the mirror root so its own name is
        # not included. Segments are collected leaf-first, then reversed.
        segments = []
        root_found = False
        for node in reversed(chain):
            if root_found:
                break
            if node.backend_id:
                root_found = True
                continue
            segments.append(node.name)
        return posixpath.join(*reversed(segments)) if segments else ""

    def _assert_writable(self):
        """Raise if this entry's backend mirror is read-only."""
        self.ensure_one()
        try:
            _, mirror_root = self._resolve_backend()
        except ValidationError:
            return
        if mirror_root.read_only:
            raise ValidationError(
                _("Backend mirror '%s' is read-only.", mirror_root.complete_name)
            )

    def _follow(self):
        """Resolve bind mounts / symlinks, returning the real entry.

        An entry with ``target_id`` is an alias for its target. Non-alias
        entries return themselves. Guarded against cycles so an alias pointing
        (directly or transitively) to itself returns the alias rather than
        looping forever.
        """
        self.ensure_one()
        seen = set()
        current = self
        while current.target_id:
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
        """Return child entries under this folder, following bind mounts.

        For a backend mirror directory the backend is first scanned so new
        backend children appear without an explicit sync (lazy mirror).
        """
        target = self._follow()
        target._sync_children()
        return self.search(
            [("parent_id", "=", target.id)], order="sequence, name"
        )

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
    # Mirror sync
    # ------------------------------------------------------------------
    def action_sync_from_backend(self):
        """Enqueue a job that materializes backend entries as file entries."""
        for entry in self:
            target = entry._follow()
            if not target.is_dir:
                continue
            target.with_delay(
                channel="root.one_storage",
                description=_("Sync folder %s") % target.complete_name,
            )._sync_from_backend()

    def _sync_children(self):
        """Lazily mirror one directory level from the backend.

        For directories inside a backend mirror, scan the backend and create
        any child entries that are missing (idempotent). No-op for entries not
        under a mirror, so plain folders are untouched.
        """
        for entry in self:
            if not entry.is_dir:
                continue
            try:
                backend, _mirror = entry._resolve_backend()
            except ValidationError:
                continue
            entry._sync_from_backend_path(backend, entry._backend_relpath())

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
            backend, _mirror = self._resolve_backend()
        except ValidationError as err:
            _logger.warning("Sync failed for %s: %s", self.complete_name, err)
            return
        self._sync_from_backend_path(backend, self._backend_relpath())

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

    def unlink(self):
        for entry in self:
            if entry.is_dir:
                if entry.child_ids:
                    raise ValidationError(
                        _("Folder '%s' is not empty.", entry.name)
                    )
                continue
            entry._assert_writable()
            backend, _mirror = entry._resolve_backend()
            rel_path = entry._backend_relpath()
            try:
                backend.delete(rel_path)
            except Exception as err:  # noqa: BLE001
                _logger.warning(
                    "Could not delete %s on backend: %s", rel_path, err
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
            if entry.is_dir:
                continue
            try:
                backend, _mirror = entry._resolve_backend()
            except ValidationError:
                continue
            rel_path = entry._backend_relpath()
            try:
                if not backend.file_exists(rel_path):
                    entry.state = "draft"
                    continue
                size = backend.get_size(rel_path)
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

        Large uploads should go through the async batch operation model or
        :meth:`write_stream` rather than this synchronous path.
        """
        for entry in self:
            if entry.is_dir:
                raise ValidationError(
                    _("Entry %s is a folder, not a file.", entry.display_name)
                )
            entry._assert_writable()
            backend, _mirror = entry._resolve_backend()
            rel_path = entry._backend_relpath()
            raw = data if binary else base64.b64decode(data)
            with backend.open(rel_path, "wb") as stream:
                stream.write(raw)
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
    def _file_backend_relpath(self):
        """Return ``(backend, rel_path)`` for this file, following aliases.

        Raises ``IsADirectoryError`` when the resolved entry is a folder.
        """
        self.ensure_one()
        real = self._follow()
        if real.is_dir:
            raise IsADirectoryError(self.complete_name)
        backend, _mirror = real._resolve_backend()
        return backend, real._backend_relpath()

    def open(self, mode="rb", **kwargs):
        """Open this file's backend stream for streaming binary I/O.

        ``mode`` is ``"rb"`` or ``"wb"`` (see :meth:`storage.backend.open`).
        """
        backend, rel_path = self._file_backend_relpath()
        return backend.open(rel_path, mode, **kwargs)

    def iter_chunks(self, chunk_size=64 * 1024):
        """Iterate this file's content in ``chunk_size``-byte chunks.

        The backend stream is resolved and opened eagerly (before the first
        chunk is read) so HTTP callers streaming the returned iterator do not
        trigger ORM/DB access after the request cursor has been released.
        """
        backend, rel_path = self._file_backend_relpath()
        ctx = backend.open(rel_path, "rb")
        stream = ctx.__enter__()

        def _chunks():
            try:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
            finally:
                ctx.__exit__(None, None, None)

        return _chunks()

    def read_bytes(self):
        """Return this file's raw bytes. Mirrors pathlib.Path.read_bytes."""
        with self.open("rb") as stream:
            return stream.read()

    def write_bytes(self, data):
        """Write raw bytes to this file, creating or overwriting it."""
        self.ensure_one()
        self._file_backend_relpath()  # raises IsADirectoryError for folders
        self.set_content(data, binary=True)
        return self

    def write_stream(self, fileobj, chunk_size=64 * 1024):
        """Stream ``fileobj`` (a binary file-like) to the backend.

        Computes checksum and size incrementally while copying, then
        refreshes metadata. Suitable for large uploads.
        """
        self.ensure_one()
        self._assert_writable()
        backend, rel_path = self._file_backend_relpath()
        digest = hashlib.sha1()
        size = 0
        with backend.open(rel_path, "wb") as stream:
            while True:
                chunk = fileobj.read(chunk_size)
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        self.write(
            {
                "file_size": size,
                "mimetype": mimetypes.guess_type(self.name)[0] or self.mimetype,
                "checksum": digest.hexdigest(),
                "state": "synced",
                "last_sync": fields.Datetime.now(),
            }
        )
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
        real = self._follow()
        if not real.is_dir:
            raise NotADirectoryError(self.complete_name)
        if parents:
            current = real
            for segment in name.split("/"):
                current = current._mkdir_step(segment)
            return current
        return real._mkdir_step(name, exist_ok=False)

    def _mkdir_step(self, name, exist_ok=True):
        self._assert_writable()
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
        real = self._follow()
        if not real.is_dir:
            raise NotADirectoryError(self.complete_name)
        real._assert_writable()
        if self.search(
            [("parent_id", "=", real.id), ("name", "=", name)], limit=1
        ):
            raise FileExistsError(self.complete_name)
        entry = self.create(
            {"name": name, "entry_type": "file", "parent_id": real.id}
        )
        if data is not None:
            entry.write_bytes(data)
        return entry

    def remove(self):
        """Delete this file and its backend bytes. Mirrors os.remove."""
        self.ensure_one()
        real = self._follow()
        if real.is_dir:
            raise IsADirectoryError(self.complete_name)
        real.unlink()

    def rmdir(self):
        """Delete this directory; it must be empty. Mirrors os.rmdir."""
        self.ensure_one()
        real = self._follow()
        if not real.is_dir:
            raise NotADirectoryError(self.complete_name)
        if real.child_ids:
            raise OSError(
                errno.ENOTEMPTY, "Directory not empty", self.complete_name
            )
        real.unlink()

    def stat(self):
        """Return metadata as a dict.

        For files, backend existence is validated (``FileNotFoundError``
        when the bytes are missing) and ``size`` is read live. Directories
        may be lazy (no backend counterpart until a file is written), so
        their stat is purely logical.
        """
        self.ensure_one()
        real = self._follow()
        if real.is_dir:
            return {
                "is_dir": True,
                "size": None,
                "mimetype": real.mimetype,
                "checksum": real.checksum,
                "mtime": real.last_sync,
            }
        backend, _mirror = real._resolve_backend()
        rel_path = real._backend_relpath()
        if not backend.file_exists(rel_path):
            raise FileNotFoundError(self.complete_name)
        return {
            "is_dir": False,
            "size": backend.get_size(rel_path),
            "mimetype": real.mimetype,
            "checksum": real.checksum,
            "mtime": real.last_sync,
        }

    def file_exists(self):
        """Whether this entry's bytes exist on the backend.

        Directories always report True (logical existence); a file reports
        False while its backend bytes are absent (state 'draft').
        """
        self.ensure_one()
        real = self._follow()
        if real.is_dir:
            return True
        try:
            backend, _mirror = real._resolve_backend()
        except ValidationError:
            return False
        return backend.file_exists(real._backend_relpath())

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
            backend, _mirror = self._resolve_backend()
            rel_path = self._backend_relpath()
            backend.delete(rel_path)
        except Exception as err:  # noqa: BLE001
            _logger.warning("Batch delete failed for %s: %s", self.complete_name, err)
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
        dest_entry = self.env["one.storage.entry"].browse(dest_entry_id)._follow()
        dest_entry._assert_writable()
        dest_backend, _dest_mirror = dest_entry._resolve_backend()
        dest_rel = dest_entry._backend_relpath()
        dest_path = posixpath.join(dest_rel, self.name) if dest_rel else self.name
        src_backend, _src_mirror = self._resolve_backend()
        src_path = self._backend_relpath()
        with src_backend.open(src_path, "rb") as src, dest_backend.open(
            dest_path, "wb"
        ) as dst:
            shutil.copyfileobj(src, dst)
        src_backend.delete(src_path)
        self.write({"parent_id": dest_entry.id})
