# Copyright 2021 ACSONE SA/NV (<http://acsone.eu>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import errno
import logging
import os
import ssl
import tempfile
from contextlib import contextmanager

from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

# Spooled temporary files hold up to this many bytes in memory before
# spilling to disk, bounding memory for large uploads/downloads.
_SPOOL_MAX_SIZE = 8 * 1024 * 1024

try:
    import ftplib
except ImportError as err:  # pragma: no cover
    _logger.debug(err)


def _ssl_protocol(name):
    # SSLv2/SSLv3 and the fixed TLSv1.x constants have been removed or
    # deprecated across Python versions. Resolve them lazily so the module
    # can be imported on any interpreter; unsupported protocols fall back
    # to a user-facing deprecation message handled by the caller.
    value = getattr(ssl, name, None)
    if value is not None:
        return value
    return f"{name} has been deprecated due to security issues"


FTP_SECURITY_TO_PROTOCOL = {
    "tls": _ssl_protocol("PROTOCOL_TLS"),
    "tlsv1": _ssl_protocol("PROTOCOL_TLSv1"),
    "tlsv1_1": _ssl_protocol("PROTOCOL_TLSv1_1"),
    "tlsv1_2": _ssl_protocol("PROTOCOL_TLSv1_2"),
    "sslv2": _ssl_protocol("PROTOCOL_SSLv2"),
    "sslv23": _ssl_protocol("PROTOCOL_SSLv23"),
    "sslv3": _ssl_protocol("PROTOCOL_SSLv3"),
}


def ftp_mkdirs(client, path):
    try:
        client.mkd(path)
    except OSError as e:
        if e.errno == errno.ENOENT and path:
            ftp_mkdirs(client, os.path.dirname(path))
            client.mkd(path)
        else:
            raise  # pragma: no cover


class ImplicitFTPTLS(ftplib.FTP_TLS):
    """
    FTP_TLS subclass that automatically wraps sockets in SSL
    to support implicit FTPS.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        """Return the socket."""
        return self._sock

    @sock.setter
    def sock(self, value):
        """When modifying the socket, ensure that it is ssl wrapped."""
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value


@contextmanager
def ftp(backend):
    security = None
    prot_p = False
    if backend.ftp_encryption in ["ftp", "tls", "tls_explicit"]:
        if backend.ftp_encryption == "ftp":
            _ftp = ftplib.FTP(timeout=30)
        elif backend.ftp_encryption == "tls":
            _ftp = ImplicitFTPTLS()
            # Due to a bug between ftplib and ssl, this part (about ssl)
            # might not work! See: https://bugs.python.org/issue31727
            security = FTP_SECURITY_TO_PROTOCOL.get(backend.ftp_security, None)
            prot_p = True
            if isinstance(security, str):
                raise UserError(security)
        elif backend.ftp_encryption == "tls_explicit":
            _ftp = ftplib.FTP_TLS(timeout=30)
            prot_p = True
        with _ftp as client:
            if security:
                client.ssl_version = security
            client.connect(host=backend.ftp_server, port=backend.ftp_port)
            client.login(backend.ftp_login, backend.ftp_password)
            if prot_p:
                client.prot_p()
            if backend.ftp_passive:
                client.set_pasv(True)
            yield client


class FTPStorageBackendAdapter(Component):
    _name = "ftp.adapter"
    _inherit = "base.storage.adapter"
    _usage = "ftp"

    @contextmanager
    def open(self, relative_path, mode="rb", **kwargs):
        full_path = self._fullpath(relative_path)
        with ftp(self.collection) as client:
            if "w" in mode:
                dirname = os.path.dirname(full_path)
                if dirname:
                    try:
                        client.cwd(dirname)
                    except OSError as e:
                        if e.errno == errno.ENOENT:
                            ftp_mkdirs(client, dirname)
                        else:
                            raise  # pragma: no cover
                with tempfile.SpooledTemporaryFile(
                    max_size=_SPOOL_MAX_SIZE, mode="w+b"
                ) as spool:
                    yield spool
                    spool.seek(0)
                    try:
                        client.storbinary("STOR " + full_path, spool)
                    except ftplib.Error as e:
                        raise ValueError(repr(e)) from e
                    except OSError as e:
                        raise ValueError(repr(e)) from e
            else:
                with tempfile.SpooledTemporaryFile(
                    max_size=_SPOOL_MAX_SIZE, mode="w+b"
                ) as spool:
                    try:
                        client.retrbinary("RETR " + full_path, spool.write)
                    except ftplib.Error as e:
                        raise FileNotFoundError(repr(e)) from e
                    spool.seek(0)
                    yield spool

    def list(self, relative_path="", limit=None, detail=False):
        full_path = self._fullpath(relative_path)
        with ftp(self.collection) as client:
            try:
                if detail:
                    try:
                        items = [
                            (name, int(facts.get("size") or 0))
                            for name, facts in client.mlsd(full_path)
                        ]
                    except (ftplib.Error, OSError, AttributeError):
                        # MLSD not supported: fall back to NLST without sizes
                        items = [(name, 0) for name in client.nlst(full_path)]
                else:
                    items = client.nlst(full_path)
            except OSError as e:
                if e.errno == errno.ENOENT:
                    # The path do not exist return an empty list
                    return []
                else:
                    raise  # pragma: no cover
        if limit:
            items = items[:limit]
        return items

    def exists(self, relative_path):
        full_path = self._fullpath(relative_path)
        with ftp(self.collection) as client:
            try:
                return client.size(full_path) is not None
            except ftplib.Error:
                return False

    def get_size(self, relative_path):
        full_path = self._fullpath(relative_path)
        with ftp(self.collection) as client:
            size = client.size(full_path)
            if size is None:
                raise FileNotFoundError(relative_path)
            return size

    def move_files(self, files, destination_path):
        _logger.debug("mv %s %s", files, destination_path)
        fp = self._fullpath
        with ftp(self.collection) as client:
            for ftp_file in files:
                dest_file_path = os.path.join(
                    destination_path, os.path.basename(ftp_file)
                )
                # Remove existing file at the destination path (an error is raised
                # otherwise)
                result = []
                try:
                    result = client.nlst(dest_file_path)
                except ftplib.Error:
                    _logger.debug("destination %s is free", dest_file_path)
                if result:
                    client.delete(dest_file_path)
                # Move the file using absolute filepaths
                client.rename(fp(ftp_file), fp(dest_file_path))

    def delete(self, relative_path):
        full_path = self._fullpath(relative_path)
        with ftp(self.collection) as client:
            return client.delete(full_path)

    def validate_config(self):
        with ftp(self.collection) as client:
            client.getwelcome()
