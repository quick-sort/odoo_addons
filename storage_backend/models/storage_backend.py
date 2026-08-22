# Copyright 2017 Akretion (http://www.akretion.com).
# @author Sébastien BEAU <sebastien.beau@akretion.com>
# Copyright 2019 Camptocamp SA (http://www.camptocamp.com).
# @author Simone Orsi <simone.orsi@camptocamp.com>
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import fnmatch
import functools
import gzip
import inspect
import logging
import warnings
from contextlib import contextmanager

from odoo import fields, models

_logger = logging.getLogger(__name__)


# TODO: useful for the whole OCA?
def deprecated(reason):
    """Mark functions or classes as deprecated.

    Emit warning at execution.

    The @deprecated is used with a 'reason'.

        .. code-block:: python

            @deprecated("please, use another function")
            def old_function(x, y):
                pass
    """

    def decorator(func1):
        if inspect.isclass(func1):
            fmt1 = "Call to deprecated class {name} ({reason})."
        else:
            fmt1 = "Call to deprecated function {name} ({reason})."

        @functools.wraps(func1)
        def new_func1(*args, **kwargs):
            warnings.simplefilter("always", DeprecationWarning)
            warnings.warn(
                fmt1.format(name=func1.__name__, reason=reason),
                category=DeprecationWarning,
                stacklevel=2,
            )
            warnings.simplefilter("default", DeprecationWarning)
            return func1(*args, **kwargs)

        return new_func1

    return decorator


class StorageBackend(models.Model):
    _name = "storage.backend"
    _inherit = ["collection.base", "server.env.mixin"]
    _backend_name = "storage_backend"
    _description = "Storage Backend"

    name = fields.Char(required=True)
    backend_type = fields.Selection(
        selection=[("filesystem", "Filesystem")], required=True, default="filesystem"
    )
    directory_path = fields.Char(
        help="Relative path to the directory to store the file"
    )
    gzip_extensions = fields.Char(
        string="Gzip Extensions",
        help="Comma-separated file extensions whose content is gzip-compressed "
        "on write and decompressed on read, e.g. csv, json. The physical path "
        "gets a '.gz' suffix; the logical path stays unchanged. Empty by "
        "default.",
    )
    has_validation = fields.Boolean(compute="_compute_has_validation")

    def _compute_has_validation(self):
        for rec in self:
            if not rec.backend_type:
                # with server_env
                # this code can be triggered
                # before a backend_type has been set
                # get_adapter() can't work without backend_type
                rec.has_validation = False
                continue
            adapter = rec._get_adapter()
            rec.has_validation = hasattr(adapter, "validate_config")

    @property
    def _server_env_fields(self):
        return {
            "backend_type": {},
            "directory_path": {},
        }

    def _gzip_extension_list(self):
        return [
            ext.strip().lower().lstrip(".")
            for ext in (self.gzip_extensions or "").split(",")
            if ext.strip()
        ]

    def _gzip_physical(self, relative_path):
        """Map a logical path to the physical one.

        For a path whose extension is in ``gzip_extensions`` the physical
        path gets a ``.gz`` suffix (mirroring the on-storage layout of the
        ``dataset_storage`` addon so existing data stays readable).
        """
        ext = relative_path.rsplit(".", 1)[-1]
        use_gzip = ext in self._gzip_extension_list()
        if use_gzip:
            return relative_path + ".gz", True
        return relative_path, False

    def _gzip_logical(self, name):
        """Reverse of ``_gzip_physical``: strip a ``.gz`` suffix that our
        write path added for a gzip-wrapped extension."""
        if name.endswith(".gz"):
            base = name[:-3]
            if base.rsplit(".", 1)[-1] in self._gzip_extension_list():
                return base
        return name

    @contextmanager
    def open(self, relative_path, mode="rb", **kwargs):
        """Open ``relative_path`` for streaming binary I/O.

        ``mode`` is ``"rb"`` (read) or ``"wb"`` (write). The logical path is
        mapped to its physical counterpart and gzip extensions are
        transparently (de)compressed. Yields a binary file-like object; the
        adapter finalizes (flush/close/upload) when the context manager exits.
        """
        self.ensure_one()
        if mode not in ("rb", "wb"):
            raise ValueError("mode must be 'rb' or 'wb', got %r" % mode)
        physical, use_gzip = self._gzip_physical(relative_path)
        with self._forward("open", physical, mode, **kwargs) as stream:
            if not use_gzip:
                yield stream
                return
            if "r" in mode:
                with gzip.GzipFile(fileobj=stream, mode="rb") as gz:
                    yield gz
            else:
                with gzip.GzipFile(fileobj=stream, mode="wb") as gz:
                    yield gz

    def list_files(self, relative_path="", pattern=False, limit=False, detail=False):
        """List ``relative_path``.

        Returns names, or with ``detail=True`` one dict per entry in the
        ``stat()`` shape (``name``, ``size``, ``is_dir``, ``mtime`` when the
        adapter provides it).
        """
        items = self._forward(
            "list", relative_path, limit=limit or None, detail=detail
        )
        if detail:
            items = [
                {**item, "name": self._gzip_logical(item["name"])}
                for item in items
            ]
        else:
            items = [self._gzip_logical(name) for name in items]
        if pattern:
            if detail:
                items = [
                    item
                    for item in items
                    if fnmatch.fnmatch(item["name"], pattern)
                ]
            else:
                items = fnmatch.filter(items, pattern)
        return items

    def find_files(self, pattern, relative_path="", **kw):
        return self._forward("find_files", pattern, relative_path=relative_path)

    def move_files(self, files, destination_path, **kw):
        return self._forward("move_files", files, destination_path, **kw)

    def rename(self, relative_path, new_path):
        """Rename/move ``relative_path`` to ``new_path`` inside the backend.

        Both paths are logical (relative to the backend root); gzip
        extensions are mapped to their physical counterparts. Native where
        the adapter supports it (atomic, works for directories), otherwise a
        stream copy + delete fallback.
        """
        physical_src, _ = self._gzip_physical(relative_path)
        physical_dst, _ = self._gzip_physical(new_path)
        return self._forward("rename", physical_src, physical_dst)

    def rmdir(self, relative_path):
        """Remove the empty directory ``relative_path`` (no-op on backends
        without real directories)."""
        return self._forward("rmdir", relative_path)

    def file_exists(self, relative_path):
        physical, _ = self._gzip_physical(relative_path)
        return self._forward("exists", physical)

    def get_size(self, relative_path):
        """Return the stored size in bytes.

        This is the size of the bytes actually on the backend (the gzip
        stream for gzip-wrapped extensions), not the decompressed length.
        """
        physical, _ = self._gzip_physical(relative_path)
        return self._forward("get_size", physical)

    def stat(self, relative_path):
        physical, _ = self._gzip_physical(relative_path)
        return self._forward("stat", physical)

    def delete(self, relative_path):
        physical, _ = self._gzip_physical(relative_path)
        return self._forward("delete", physical)

    def _forward(self, method, *args, **kwargs):
        _logger.debug(
            "Backend Storage ID: %s type %s: %s file %s %s",
            self.backend_type,
            self.id,
            method,
            args,
            kwargs,
        )
        self.ensure_one()
        adapter = self._get_adapter()
        return getattr(adapter, method)(*args, **kwargs)

    def _get_adapter(self):
        with self.work_on(self._name) as work:
            return work.component(usage=self.backend_type)

    def action_test_config(self):
        self.ensure_one()
        if not self.has_validation:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Connection Test Skipped!"),
                    "message": self.env._(
                        "This storage type does not support connection testing."
                    ),
                    "type": "warning",
                    "sticky": False,
                },
            }
        adapter = self._get_adapter()
        try:
            adapter.validate_config()
            title = self.env._("Connection Test Succeeded!")
            message = self.env._("Everything seems properly set up!")
            msg_type = "success"
        except Exception as err:
            title = self.env._("Connection Test Failed!")
            message = str(err)
            msg_type = "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": msg_type,
                "sticky": False,
            },
        }
