# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Unified inode-like entry model.

A single ``one.storage.entry`` represents either a directory (``is_dir``) or
a file inside the virtual folder tree, mirroring a real filesystem inode.

A directory that carries a ``backend_id`` is the **root of a backend mirror**:
its subtree mirrors that ``storage.backend`` (root ``/``). Files created under
it are stored in that backend; their relative path is derived on demand from
their logical path under the mirror root.

**Bind mounts**: any directory whose ``binding_id`` points at a backend root
entry becomes an alias for that mirror — listing, reading and writing it
transparently operates on the mirror tree. One backend root can be the target
of many directories, so the same backend can appear at several paths.
``_follow`` resolves a bind (or symlink) to the real entry behind it.
"""

import base64
import errno
import fnmatch
import hashlib
import logging
import mimetypes
import posixpath
import shutil

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_FORBIDDEN_NAME_CHARS = ("/", "\\", "\0")


def _validate_entry_name(name):
    """Raise ``ValidationError`` unless ``name`` is a valid entry name."""
    if (
        not name
        or name != name.strip()
        or name in (".", "..")
        or any(char in name for char in _FORBIDDEN_NAME_CHARS)
    ):
        raise ValidationError(
            _(
                "Invalid name '%(name)s': names cannot be empty or '.'/'..', "
                "cannot start or end with whitespace and cannot contain "
                "'/', '\\' or null characters.",
                name=name,
            )
        )


class OneStorageEntry(models.Model):
    """A directory, file or symlink in the virtual folder tree."""

    _name = "one.storage.entry"
    _description = "One Storage Entry"
    _order = "sequence, name"
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
    child_count = fields.Integer(
        compute="_compute_child_count",
        string="Sub-entries",
    )
    parent_path = fields.Char(index=True)
    complete_name = fields.Char(
        compute="_compute_complete_name",
        store=True,
        recursive=True,
    )

    # The backend this subtree lives on is not stored on entries: each
    # backend owns its mirror root (storage.backend.entry_id), and entries
    # resolve their backend by matching ancestors against those roots.
    # Displayed via the computed backend_id below.
    backend_id = fields.Many2one(
        comodel_name="storage.backend",
        compute="_compute_backend_id",
        store=True,
        recursive=True,
        help="Storage backend this entry's bytes live on. Computed from the "
        "backend owning the nearest mirror-root ancestor.",
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
    state = fields.Selection(
        selection=[("draft", "Draft"), ("synced", "Synced"), ("error", "Error")],
        default="draft",
    )
    last_sync = fields.Datetime()

    # A directory whose ``binding_id`` points at a backend mirror root is a
    # bind mount (an alias) for that mirror tree.
    binding_id = fields.Many2one(
        comodel_name="one.storage.entry",
        help="Mirror-root entry this folder is bound to. Operating on this "
        "entry transparently operates on the bound mirror tree. One root may "
        "be bound at many folders, so a backend can appear at several paths.",
    )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    @api.depends("entry_type")
    def _compute_is_dir(self):
        for entry in self:
            entry.is_dir = entry.entry_type == "directory"

    @api.depends("child_ids")
    def _compute_child_count(self):
        for entry in self:
            entry.child_count = len(entry.child_ids)

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for entry in self:
            if entry.parent_id:
                entry.complete_name = posixpath.join(
                    entry.parent_id.complete_name or "", entry.name
                )
            else:
                entry.complete_name = "/" + entry.name if entry.name else "/"

    @api.depends("parent_id", "parent_id.backend_id", "binding_id")
    def _compute_backend_id(self):
        """Mirror-root ancestors stamp their backend onto the subtree.

        The stored mirror root itself carries its backend here too — its
        ``parent_id.backend_id`` is empty, but ``storage.backend.entry_id``
        points at it, so we check both sources. A bind mount follows its
        ``binding_id``: the folder shows the mounted backend, and its children
        inherit it through ``parent_id``. Stored (not plain compute) because
        kanban lists read it for every card.
        """
        for entry in self:
            backend = self.env["storage.backend"].sudo().search(
                [("entry_id", "=", entry.id)], limit=1
            )
            if not backend and entry.binding_id:
                backend = entry.binding_id.backend_id
            entry.backend_id = backend or entry.parent_id.backend_id

    @api.constrains("name")
    def _check_name_validity(self):
        for entry in self:
            _validate_entry_name(entry.name)

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
        if self._has_cycle("parent_id"):
            raise ValidationError(_("Folder hierarchy must not contain cycles."))

    @api.constrains("binding_id")
    def _check_target_not_descendant(self):
        """A bind mount must not point into its own subtree."""
        for entry in self:
            if not entry.binding_id:
                continue
            prefix = entry.parent_path and entry.parent_path + "/"
            if prefix and (entry.binding_id.parent_path or "").startswith(prefix):
                raise ValidationError(
                    _(
                        "An entry cannot be an alias for one of its own "
                        "descendants ('%s').",
                        entry.name,
                    )
                )

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

        Each backend owns its mirror root via ``storage.backend.entry_id``
        (few backends, so this is a small indexed lookup). Walk the ancestor
        chain from the leaf up and return the first node that some backend
        claims as its mirror root.
        """
        self.ensure_one()
        ids = [int(x) for x in (self.parent_path or "").split("/") if x]
        claims = {
            backend.entry_id.id: backend
            for backend in self.env["storage.backend"].sudo().search(
                [("entry_id", "in", ids)]
            )
        }
        for node_id in reversed(ids):
            if node_id in claims:
                backend = claims[node_id]
                return backend, self.browse(node_id)
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
        ids = [int(x) for x in (self.parent_path or "").split("/") if x]
        claims = {
            backend.entry_id.id
            for backend in self.env["storage.backend"].sudo().search(
                [("entry_id", "in", ids)]
            )
        }
        # Walk from the leaf up; stop after the mirror root so its own name
        # is not included. Segments are collected leaf-first, then reversed.
        chain = {node.id: node for node in self.browse(ids)}
        segments = []
        root_found = False
        for node_id in reversed(ids):
            node = chain[node_id]
            if root_found:
                break
            if node_id in claims:
                root_found = True
                continue
            segments.append(node.name)
        return posixpath.join(*reversed(segments)) if segments else ""

    def _assert_writable(self):
        """Raise if this entry's backend mirror is read-only."""
        self.ensure_one()
        try:
            _backend, mirror_root = self._resolve_backend()
        except ValidationError:
            return
        if mirror_root.read_only:
            raise ValidationError(
                _("Backend mirror '%s' is read-only.", mirror_root.complete_name)
            )

    def _follow(self):
        """Resolve bind mounts / symlinks, returning the real entry.

        An entry with ``binding_id`` is an alias for its target. Non-alias
        entries return themselves. Guarded against cycles so an alias pointing
        (directly or transitively) to itself returns the alias rather than
        looping forever.
        """
        self.ensure_one()
        seen = set()
        current = self
        while current.binding_id:
            if current.id in seen:
                break
            seen.add(current.id)
            current = current.binding_id
        return current

    def resolve_path(self, segments):
        """Walk ``segments`` down the tree from this entry.

        Returns the deepest ``one.storage.entry`` reached. Symlinks are
        followed transparently (POSIX semantics). Raises
        ``FileNotFoundError`` for an unknown name and ``NotADirectoryError``
        when an intermediate segment names a file.
        """
        current = self._follow()
        for index, segment in enumerate(segments):
            child = self.search(
                [("parent_id", "=", current.id), ("name", "=", segment)], limit=1
            )
            if not child:
                raise FileNotFoundError(errno.ENOENT, segment)
            child = child._follow()
            if not child.is_dir and index != len(segments) - 1:
                raise NotADirectoryError(errno.ENOTDIR, segment)
            current = child
        return current

    def list_children(self, sync=True):
        """Return child entries under this folder, following bind mounts.

        When ``sync`` is true (default) a backend mirror directory is first
        scanned so new backend children appear without an explicit sync (lazy
        mirror). Programmatic callers that only want the logical tree can
        pass ``sync=False`` to skip the backend round-trip.
        """
        target = self._follow()
        if sync:
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
        root = self.create({"name": "One Storage", "entry_type": "directory"})
        backend.entry_id = root
        return root

    def _get_or_create_mirror_root(self, backend):
        """Return the persistent mirror root entry for ``backend``.

        Each backend owns one hidden directory (``active=False``, child of
        the global root, referenced by ``backend.entry_id``) that mirrors its
        ``/``. Mounting a backend binds a user-facing folder to this entry
        (``binding_id``), so the mirrored tree survives unmount/remount
        without rescanning the backend. The tree itself is filled lazily,
        one level per listing.
        """
        if backend.entry_id:
            return backend.entry_id
        root = self._get_or_create_root()
        mirror = self.create(
            {
                "name": backend.name,
                "entry_type": "directory",
                "parent_id": root.id,
                "active": False,
            }
        )
        backend.entry_id = mirror
        return mirror

    def action_open_children(self):
        """Card click handler for the file browser.

        Directories are lazily synced (one level) then descended
        (breadcrumb-able); files open their form view. Symlinks are followed
        to their target first. Used as ``<kanban action="action_open_children"
        type="object">`` so the whole card is clickable.
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
        target._sync_children()
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
    def _sync_children(self):
        """Lazily mirror one directory level from the backend.

        For directories inside a backend mirror, scan the backend and create
        any child entries that are missing, refresh the metadata of known
        files and prune previously-synced files whose backend bytes are gone
        (idempotent). No-op for entries not under a mirror, so plain folders
        are untouched.
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
        self._sync_from_backend_path(
            backend, self._backend_relpath(), recursive=True
        )

    def _backend_child_is_dir(self, backend, child_path):
        """Whether a backend child path is a directory.

        Prefers ``stat`` (one call on backends that support it); falls back
        to the list probe (non-empty listing = directory) which works on
        every backend.
        """
        try:
            info = backend.stat(child_path)
            if isinstance(info, dict) and "is_dir" in info:
                return bool(info["is_dir"])
        except Exception:  # noqa: BLE001 - no stat support or missing path
            pass
        return bool(backend.list_files(child_path))

    def _sync_from_backend_path(self, backend, rel_path, recursive=False):
        """Sync one directory level of ``backend`` under ``self``.

        ``rel_path`` is this entry's path inside ``backend``. Each backend
        child is created as a file or directory entry (or refreshed when it
        already exists). With ``recursive`` (explicit sync) subdirectories
        are recursed into with their explicit path; by default (lazy
        listing) subdirectories are created empty and filled when the user
        descends into them. Files that were previously synced but no longer
        exist on the backend are pruned.
        """
        self.ensure_one()
        try:
            entries = backend.list_files(rel_path, detail=True)
        except Exception as err:  # noqa: BLE001
            _logger.warning("Sync failed for %s: %s", self.complete_name, err)
            return
        existing = {child.name: child for child in self.child_ids}
        backend_names = set()
        for entry_name, size in entries:
            # S3 adapters report directories as names with a trailing slash.
            entry_name = entry_name.rstrip("/")
            backend_names.add(entry_name)
            child_path = posixpath.join(rel_path, entry_name) if rel_path else entry_name
            is_subdir = self._backend_child_is_dir(backend, child_path)
            child = existing.get(entry_name)
            if child is None:
                child = self.env["one.storage.entry"].create(
                    {
                        "name": entry_name,
                        "entry_type": "directory" if is_subdir else "file",
                        "parent_id": self.id,
                        "file_size": size or 0,
                        "mimetype": mimetypes.guess_type(entry_name)[0],
                        "state": "synced",
                        "last_sync": fields.Datetime.now(),
                    }
                )
            elif not child.is_dir and not is_subdir:
                child.write(
                    {
                        "file_size": size or 0,
                        "mimetype": child.mimetype
                        or mimetypes.guess_type(entry_name)[0],
                        "state": "synced",
                        "last_sync": fields.Datetime.now(),
                    }
                )
            # Lazily (default) subdirectories are created empty: their level
            # is pulled when the user descends into them, so a huge backend
            # never triggers a recursive full scan on listing.
            if recursive and is_subdir:
                child._sync_from_backend_path(backend, child_path, recursive=True)
        # Prune files whose backend bytes disappeared while they were away.
        # Draft entries are kept: they may be placeholders whose bytes were
        # never pushed. Directories are kept too: logical (empty) folders
        # have no backend counterpart.
        for name, child in existing.items():
            if name in backend_names or child.is_dir or child.state != "synced":
                continue
            try:
                child.unlink()
            except ValidationError as err:
                _logger.warning(
                    "Prune of %s skipped: %s", child.complete_name, err
                )

    # ------------------------------------------------------------------
    # CRUD hooks: keep the backend in sync with entry lifecycle
    # ------------------------------------------------------------------
    def unlink(self):
        skip_backend = self.env.context.get("one_storage_skip_backend_sync")
        for entry in self:
            entry._assert_writable()
            if entry.is_dir:
                if entry.child_ids:
                    raise ValidationError(
                        _("Folder '%s' is not empty.", entry.name)
                    )
                continue
            if skip_backend:
                continue
            backend, _mirror = entry._resolve_backend()
            rel_path = entry._backend_relpath()
            try:
                backend.delete(rel_path)
            except Exception as err:  # noqa: BLE001
                _logger.warning(
                    "Could not delete %s on backend: %s", rel_path, err
                )
        return super().unlink()

    def write(self, vals):
        """Propagate name/parent changes to the backend storage.

        Renaming an entry (or moving it inside the same backend mirror)
        renames its bytes on the backend via ``storage.backend.rename``, so
        the logical tree and the stored bytes never drift apart. Moving
        across backends is not possible through plain ``write`` — use
        :meth:`move`, which streams the bytes over first.
        """
        if self.env.context.get("one_storage_skip_backend_sync") or (
            "name" not in vals and "parent_id" not in vals
        ):
            return super().write(vals)
        pending = []
        for entry in self:
            try:
                backend, _mirror = entry._resolve_backend()
            except ValidationError:
                continue
            old_rel = entry._backend_relpath()
            new_name = vals.get("name") or entry.name
            new_parent_id = (
                vals["parent_id"] if "parent_id" in vals else entry.parent_id.id
            )
            if new_name == entry.name and new_parent_id == entry.parent_id.id:
                continue
            if "parent_id" in vals and new_parent_id != entry.parent_id.id:
                new_parent = self.browse(new_parent_id)
                new_backend = None
                if new_parent:
                    try:
                        new_backend, _m = new_parent._resolve_backend()
                    except ValidationError:
                        new_backend = None
                if new_backend is None or new_backend.id != backend.id:
                    raise ValidationError(
                        _(
                            "Moving '%s' across storage backends requires "
                            "entry.move().",
                            entry.complete_name,
                        )
                    )
            pending.append((backend, old_rel, entry))
        res = super().write(vals)
        for backend, old_rel, entry in pending:
            new_rel = entry._backend_relpath()
            if new_rel == old_rel:
                continue
            try:
                backend.rename(old_rel, new_rel)
            except FileNotFoundError:
                # Draft file never pushed to the backend; nothing to rename.
                _logger.debug(
                    "No backend bytes to rename for %s", entry.complete_name
                )
        return res

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------
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
        Write mode is rejected on read-only mirrors.
        """
        backend, rel_path = self._file_backend_relpath()
        if "w" in mode:
            self._follow()._assert_writable()
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

    def read_text(self, encoding="utf-8"):
        """Return this file's content decoded as text."""
        return self.read_bytes().decode(encoding)

    def write_text(self, text, encoding="utf-8"):
        """Write ``text`` to this file, creating or overwriting it."""
        return self.write_bytes(text.encode(encoding))

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

    def rename(self, new_name):
        """Rename this entry in place (same parent) and on the backend.

        Mirrors ``os.rename`` for the single-directory case; use
        :meth:`move` to change parents. Raises ``FileExistsError`` when the
        new name is taken and propagates name validation errors.
        """
        self.ensure_one()
        new_name = (new_name or "").strip()
        try:
            _validate_entry_name(new_name)
        except ValidationError as err:
            raise OSError(errno.EINVAL, str(err)) from err
        real = self._follow()
        if new_name == real.name:
            return real
        clash = self.search(
            [
                ("parent_id", "=", real.parent_id.id),
                ("name", "=", new_name),
                ("id", "!=", real.id),
            ],
            limit=1,
        )
        if clash:
            raise FileExistsError(errno.EEXIST, new_name)
        real.write({"name": new_name})
        return real

    def move(self, dest_dir):
        """Move this entry (and its subtree) under ``dest_dir``.

        Same-backend moves rename on the backend (atomic, directories
        included). Cross-backend moves stream every file to the destination
        backend and delete the source bytes. Raises ``NotADirectoryError``
        when the destination is a file, ``FileExistsError`` on a name clash
        and ``OSError(EINVAL)`` when moving a folder into its own subtree.
        """
        self.ensure_one()
        real = self._follow()
        dest = dest_dir._follow()
        if not dest.is_dir:
            raise NotADirectoryError(errno.ENOTDIR, dest_dir.complete_name)
        if real.parent_id.id == dest.id:
            return real
        if real.is_dir:
            prefix = real.parent_path and real.parent_path + "/"
            if prefix and (dest.parent_path or "").startswith(prefix):
                raise OSError(
                    errno.EINVAL,
                    "Cannot move a folder into its own subtree",
                    real.complete_name,
                )
        real._assert_writable()
        dest._assert_writable()
        if self.search(
            [("parent_id", "=", dest.id), ("name", "=", real.name)], limit=1
        ):
            raise FileExistsError(errno.EEXIST, real.name)
        src_backend, _src_mirror = real._resolve_backend()
        dst_backend, _dst_mirror = dest._resolve_backend()
        src_rel = real._backend_relpath()
        dst_rel = posixpath.join(dest._backend_relpath(), real.name)
        if src_backend.id == dst_backend.id:
            if src_rel != dst_rel:
                try:
                    src_backend.rename(src_rel, dst_rel)
                except FileNotFoundError:
                    _logger.debug(
                        "No backend bytes to move for %s", real.complete_name
                    )
        else:
            if real.is_dir:
                real._copy_backend_tree(dst_backend, dst_rel)
                real._delete_backend_tree()
            elif real.file_exists():
                with src_backend.open(src_rel, "rb") as src, dst_backend.open(
                    dst_rel, "wb"
                ) as dst:
                    shutil.copyfileobj(src, dst)
                src_backend.delete(src_rel)
        real.with_context(one_storage_skip_backend_sync=True).write(
            {"parent_id": dest.id}
        )
        return real

    def _copy_backend_tree(self, dst_backend, dst_rel):
        """Stream this entry's bytes (recursively for folders) to a backend."""
        if self.is_dir:
            for child in self.child_ids:
                child_rel = posixpath.join(dst_rel, child.name)
                child._copy_backend_tree(dst_backend, child_rel)
            return
        if not self.file_exists():
            return
        src_backend, _mirror = self._resolve_backend()
        with src_backend.open(self._backend_relpath(), "rb") as src, dst_backend.open(
            dst_rel, "wb"
        ) as dst:
            shutil.copyfileobj(src, dst)

    def _delete_backend_tree(self):
        """Delete this entry's bytes (recursively for folders) from its backend."""
        if self.is_dir:
            for child in self.child_ids:
                child._delete_backend_tree()
            try:
                backend, _mirror = self._resolve_backend()
            except ValidationError:
                return
            try:
                backend.rmdir(self._backend_relpath())
            except Exception as err:  # noqa: BLE001
                _logger.warning(
                    "Could not remove %s on backend: %s",
                    self._backend_relpath(),
                    err,
                )
            return
        try:
            backend, _mirror = self._resolve_backend()
        except ValidationError:
            return
        try:
            backend.delete(self._backend_relpath())
        except Exception as err:  # noqa: BLE001
            _logger.warning(
                "Could not delete %s on backend: %s",
                self._backend_relpath(),
                err,
            )

    def copy_to(self, dest_dir, new_name=None):
        """Copy this entry (recursively for folders) under ``dest_dir``.

        Bytes are always physically copied (even within the same backend),
        so the copy is independent of the source. Returns the new entry.
        """
        self.ensure_one()
        dest = dest_dir._follow()
        if not dest.is_dir:
            raise NotADirectoryError(errno.ENOTDIR, dest_dir.complete_name)
        dest._assert_writable()
        real = self._follow()
        name = new_name or real.name
        if self.search(
            [("parent_id", "=", dest.id), ("name", "=", name)], limit=1
        ):
            raise FileExistsError(errno.EEXIST, name)
        if real.is_dir:
            new_dir = self.create(
                {"name": name, "entry_type": "directory", "parent_id": dest.id}
            )
            for child in real.child_ids:
                child.copy_to(new_dir)
            return new_dir
        dst_backend, _dst_mirror = dest._resolve_backend()
        dst_rel = posixpath.join(dest._backend_relpath(), name)
        if real.file_exists():
            src_backend, _src_mirror = real._resolve_backend()
            with src_backend.open(
                real._backend_relpath(), "rb"
            ) as src, dst_backend.open(dst_rel, "wb") as dst:
                shutil.copyfileobj(src, dst)
        entry = self.create(
            {"name": name, "entry_type": "file", "parent_id": dest.id}
        )
        entry._refresh_metadata()
        return entry

    def glob(self, pattern):
        """Return direct children whose name matches ``pattern`` (fnmatch).

        Single-level, like ``Path.glob`` with a flat pattern; children of
        bind mounts are included, the backend is not re-scanned.
        """
        return self.list_children(sync=False).filtered(
            lambda child: fnmatch.fnmatch(child.name, pattern)
        )

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

    def rmtree(self):
        """Delete this directory and everything below it.

        Mirrors ``shutil.rmtree``: children are deleted depth-first (backend
        bytes first, then the entries), so the tree is removed whether or not
        it still matches the backend layout.
        """
        self.ensure_one()
        real = self._follow()
        if not real.is_dir:
            raise NotADirectoryError(errno.ENOTDIR, self.complete_name)
        real._assert_writable()
        for child in real.child_ids:
            if child.is_dir:
                child.rmtree()
            else:
                child.remove()
        real.unlink()

    def _drop_children(self):
        """Delete the subtree's entries depth-first, backend bytes untouched.

        Used by unmount: the mirror's entries disappear from the tree while
        the backend keeps its files, so a later re-mount finds them again.
        """
        self.ensure_one()
        for child in self.child_ids:
            if child.is_dir:
                child._drop_children()
            child.unlink()

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

    def action_rename(self):
        """Open the rename wizard."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Rename"),
            "res_model": "one.storage.entry.rename.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_entry_id": self.id},
        }

    def action_move(self):
        """Open the move wizard for this entry (used from card menus)."""
        return self.action_move_selected()

    def action_move_selected(self):
        """Open the move wizard for the selected entries."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Move Entries"),
            "res_model": "one.storage.entry.move.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_entry_ids": [(6, 0, self.ids)]},
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
            "context": {"default_entry_ids": [(6, 0, self.ids)]},
        }

    def action_delete_selected(self):
        """Open the delete confirmation wizard for the selected entries."""
        return self.action_delete_multi()

    def action_delete_multi(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Delete Entries"),
            "res_model": "one.storage.entry.delete.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_entry_ids": [(6, 0, self.ids)]},
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

    def action_mount_wizard(self):
        """Open the mount/unmount wizard for this folder."""
        self.ensure_one()
        real = self._follow()
        mounted_backend = real.binding_id.backend_id or real.backend_id
        return {
            "type": "ir.actions.act_window",
            "name": _("Unmount Backend") if mounted_backend else _("Mount Backend"),
            "res_model": "one.storage.entry.mount.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_entry_id": self.id,
                "default_backend_id": mounted_backend.id,
                "default_read_only": real.read_only,
            },
        }

    # ------------------------------------------------------------------
    # Async batch operations (queue_job)
    # ------------------------------------------------------------------
    def action_batch_delete(self):
        for entry in self:
            delayable = entry.with_delay(
                channel="root.one_storage",
                description=_("Delete %s") % entry.display_name,
            )
            if entry.is_dir:
                delayable._batch_rmtree()
            else:
                delayable._batch_delete()

    def _batch_delete(self):
        self.ensure_one()
        try:
            backend, _mirror = self._resolve_backend()
            rel_path = self._backend_relpath()
            backend.delete(rel_path)
        except Exception as err:  # noqa: BLE001
            _logger.warning("Batch delete failed for %s: %s", self.complete_name, err)
        self.unlink()

    def _batch_rmtree(self):
        self.ensure_one()
        self.rmtree()

    def action_batch_move(self, dest_entry):
        for entry in self:
            if not dest_entry.is_dir:
                continue
            entry.with_delay(
                channel="root.one_storage",
                description=_("Move %s") % entry.display_name,
            )._batch_move(dest_entry.id)

    def _batch_move(self, dest_entry_id):
        self.ensure_one()
        dest_entry = self.env["one.storage.entry"].browse(dest_entry_id)
        self.move(dest_entry)
