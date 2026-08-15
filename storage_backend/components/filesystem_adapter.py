# Copyright 2017 Akretion (http://www.akretion.com).
# @author Sébastien BEAU <sebastien.beau@akretion.com>
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import logging
import os
import shutil
import stat as stat_mod
from contextlib import contextmanager

from odoo.exceptions import AccessError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


def is_safe_path(basedir, path):
    """True when ``path`` resolves inside ``basedir``.

    Both sides are canonicalized and the boundary is enforced at a path
    separator, so a sibling directory that merely shares the base name
    prefix (e.g. ``storage2`` vs ``storage``) can never pass.
    """
    basedir = os.path.realpath(basedir)
    full_path = os.path.realpath(path)
    return full_path == basedir or full_path.startswith(basedir + os.sep)


class FileSystemStorageBackend(Component):
    _name = "filesystem.adapter"
    _inherit = "base.storage.adapter"
    _usage = "filesystem"

    def _basedir(self):
        return os.path.join(self.env["ir.attachment"]._filestore(), "storage")

    def _fullpath(self, relative_path):
        """This will build the full path for the file, we force to
        store the data inside the filestore in the directory 'storage".
        Becarefull if you implement your own custom path, end user
        should never be able to write or read unwanted filesystem file"""
        full_path = super()._fullpath(relative_path)
        base_dir = self._basedir()
        full_path = os.path.join(base_dir, full_path)
        if not is_safe_path(base_dir, full_path):
            raise AccessError(self.env._("Access to %s is forbidden") % full_path)
        return full_path

    @contextmanager
    def open(self, relative_path, mode="rb", **kwargs):
        full_path = self._fullpath(relative_path)
        if "w" in mode:
            dirname = os.path.dirname(full_path)
            if not os.path.isdir(dirname):
                os.makedirs(dirname)
        with open(full_path, mode) as my_file:
            yield my_file

    def list(self, relative_path="", limit=None, detail=False):
        full_path = self._fullpath(relative_path)
        if not os.path.isdir(full_path):
            return []
        with os.scandir(full_path) as entries:
            items = []
            for entry in entries:
                if detail:
                    items.append((entry.name, entry.stat().st_size))
                else:
                    items.append(entry.name)
        if limit:
            items = items[:limit]
        return items

    def exists(self, relative_path):
        return os.path.exists(self._fullpath(relative_path))

    def get_size(self, relative_path):
        return os.path.getsize(self._fullpath(relative_path))

    def stat(self, relative_path):
        full_path = self._fullpath(relative_path)
        info = os.stat(full_path)
        return {
            "size": info.st_size,
            "is_dir": stat_mod.S_ISDIR(info.st_mode),
            "mtime": info.st_mtime,
            "mode": info.st_mode,
        }

    def delete(self, relative_path):
        full_path = self._fullpath(relative_path)
        try:
            os.remove(full_path)
        except FileNotFoundError:
            _logger.warning("File not found in %s", full_path)

    def validate_config(self):
        # Ensure the basedir exists (created on demand, just like add() does).
        base_dir = self._basedir()
        if not os.path.isdir(base_dir):
            try:
                os.makedirs(base_dir, exist_ok=True)
            except OSError as err:
                raise AccessError(
                    self.env._("Could not create directory %s: %s") % (base_dir, err)
                ) from err
        # Prove we can actually store and remove a file by writing a probe
        # through the same path the real operations use, then cleaning it up.
        probe_name = ".storage_backend_probe_%d_%d" % (os.getpid(), id(base_dir))
        try:
            with self.open(probe_name, "wb") as probe_file:
                probe_file.write(b"storage backend connection test")
        except OSError as err:
            raise AccessError(
                self.env._("Could not write to directory %s: %s") % (base_dir, err)
            ) from err
        finally:
            try:
                self.delete(probe_name)
            except OSError:
                _logger.warning("Could not remove probe file %s", probe_name)

    def move_files(self, files, destination_path):
        result = []
        for file_path in files:
            if not os.path.exists(destination_path):
                os.makedirs(destination_path)
            filename = os.path.basename(file_path)
            destination_file = os.path.join(destination_path, filename)
            result.append(shutil.move(file_path, destination_file))
        return result

    def rename(self, relative_path, new_path):
        full_path = self._fullpath(relative_path)
        new_full_path = self._fullpath(new_path)
        dirname = os.path.dirname(new_full_path)
        if dirname and not os.path.isdir(dirname):
            os.makedirs(dirname)
        return os.rename(full_path, new_full_path)

    def rmdir(self, relative_path):
        full_path = self._fullpath(relative_path)
        try:
            os.rmdir(full_path)
        except FileNotFoundError:
            _logger.warning("Directory not found in %s", full_path)
