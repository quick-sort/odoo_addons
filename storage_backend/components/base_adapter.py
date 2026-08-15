# Copyright 2017 Akretion (http://www.akretion.com).
# @author Sébastien BEAU <sebastien.beau@akretion.com>
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
# Copyright 2020 ACSONE SA/NV (<http://acsone.eu>)
# @author Simone Orsi <simahawk@gmail.com>

import os
import re
import shutil
from contextlib import contextmanager

from odoo.exceptions import AccessError

from odoo.addons.component.core import AbstractComponent


class BaseStorageAdapter(AbstractComponent):
    _name = "base.storage.adapter"
    _collection = "storage.backend"

    def _check_relative_path(self, relative_path):
        """Reject logical paths that could escape the backend root.

        ``relative_path`` is the caller-supplied path inside the backend, so
        it must be relative and stay within the root: absolute paths, ``..``
        components and backslashes (ambiguous on remote/Windows-style
        backends) are forbidden. Every adapter funnels its entry points
        through ``_fullpath``, so this single check protects the filesystem,
        FTP and SFTP adapters alike.
        """
        if not isinstance(relative_path, str):
            raise AccessError(self.env._("Invalid path %r") % (relative_path,))
        if not relative_path:
            return
        if os.path.isabs(relative_path) or "\\" in relative_path:
            raise AccessError(self.env._("Access to %s is forbidden") % relative_path)
        if ".." in relative_path.split("/"):
            raise AccessError(self.env._("Access to %s is forbidden") % relative_path)

    def _fullpath(self, relative_path):
        self._check_relative_path(relative_path)
        dp = self.collection.directory_path
        if not dp or relative_path.startswith(dp):
            return relative_path
        return os.path.join(dp, relative_path)

    @contextmanager
    def open(self, relative_path, mode="rb", **kwargs):
        """Open ``relative_path`` for streaming binary I/O.

        :param relative_path: logical path of the file inside the backend
        :param mode: ``"rb"`` (read) or ``"wb"`` (write)
        :return: a binary file-like object; the adapter finalizes
                 (flush/close/upload) when the context manager exits.
        """
        raise NotImplementedError

    def list(self, relative_path="", limit=None, detail=False):
        """List entries in ``relative_path``.

        :param relative_path: optional relative path containing files
        :param limit: max number of entries to return
        :param detail: return ``(name, size)`` pairs when True, names otherwise
        """
        raise NotImplementedError

    def exists(self, relative_path):
        raise NotImplementedError

    def get_size(self, relative_path):
        raise NotImplementedError

    def stat(self, relative_path):
        """Return metadata for ``relative_path``.

        :param relative_path: path to inspect
        :return: dict with at least ``size`` (bytes) and ``is_dir`` (bool);
                 adapters may add ``mtime`` (epoch seconds) and other fields.
        """
        raise NotImplementedError

    def find_files(self, pattern, relative_path="", **kwargs):
        """Find files matching given pattern.

        :param pattern: regex expression
        :param relative_path: optional relative path containing files
        :return: list of file paths as full paths from the root
        """
        regex = re.compile(pattern)
        filelist = self.list(relative_path)
        files_matching = [
            regex.match(file_).group() for file_ in filelist if regex.match(file_)
        ]
        filepaths = []
        if files_matching:
            filepaths = [
                os.path.join(self._fullpath(relative_path) or "", filename)
                for filename in files_matching
            ]
        return filepaths

    def move_files(self, files, destination_path, **kwargs):
        """Move files to given destination.

        :param files: list of file paths to be moved
        :param destination_path: directory path where to move files
        :return: None
        """
        raise NotImplementedError

    def rename(self, relative_path, new_path):
        """Rename/move ``relative_path`` to ``new_path`` inside the backend.

        The default implementation streams the file through open() and
        deletes the source, so every adapter gets working file renames for
        free. Adapters with a native primitive (os.rename, SFTP rename, ...)
        should override it — the native version is atomic and also works for
        directories. Both paths are relative to the backend root and may
        include directory components (``a/b.txt`` → ``c/d.txt`` moves the
        file into ``c``); missing destination parents are created.

        :raise FileNotFoundError: when the source does not exist
        """
        with self.open(relative_path, "rb") as src, self.open(new_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        self.delete(relative_path)

    def rmdir(self, relative_path):
        """Remove the empty directory ``relative_path``.

        Default no-op: on backends without real directories (object stores)
        there is nothing to remove. Adapters with a directory primitive
        should override it (e.g. ``os.rmdir``) and remove the directory if
        it exists and is empty.
        """
        return None

    def delete(self, relative_path):
        raise NotImplementedError

    # You can define `validate_config` on your own adapter
    # to make validation button available on UI.
    # This method should simply pass smoothly when validation is ok,
    # otherwise it should raise an exception.
    # def validate_config(self):
    #    raise NotImplementedError
