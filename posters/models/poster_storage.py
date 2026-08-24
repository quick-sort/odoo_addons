import json
import logging

import fsspec

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class PosterStorage(models.Model):
    _name = 'poster.storage'
    _description = 'Poster File Storage'

    name = fields.Char(required=True)
    protocol = fields.Selection(
        [
            ('file', 'Local'),
            ('s3', 'Amazon S3'),
            ('gcs', 'Google Cloud Storage'),
            ('abfs', 'Azure Blob Storage'),
            ('sftp', 'SFTP'),
            ('ftp', 'FTP'),
            ('http', 'HTTP/HTTPS'),
        ],
        required=True,
        default='file',
    )
    path_prefix = fields.Char(
        required=True,
        help='Base path prefix, e.g. s3://bucket/posters/ or /mnt/data/posters/',
    )
    storage_options = fields.Text(
        default='{}',
        help='JSON dict passed as **kwargs to fsspec (credentials, region, etc.)',
    )
    active = fields.Boolean(default=True)

    @api.constrains('storage_options')
    def _check_storage_options_json(self):
        for rec in self:
            if rec.storage_options:
                try:
                    json.loads(rec.storage_options)
                except json.JSONDecodeError as e:
                    raise models.ValidationError(f'storage_options is not valid JSON: {e}') from e

    def _get_options(self):
        self.ensure_one()
        try:
            return json.loads(self.storage_options or '{}')
        except json.JSONDecodeError:
            return {}

    def _full_path(self, path):
        """Combine path_prefix and relative path into a full fsspec URI."""
        self.ensure_one()
        prefix = self.path_prefix.rstrip('/')
        clean = path.lstrip('/') if path else ''
        return f'{prefix}/{clean}' if clean else prefix

    def open(self, path, mode='rb'):
        """Return a file-like object for the given relative path."""
        self.ensure_one()
        opts = self._get_options()
        return fsspec.open(self._full_path(path), mode, **opts)

    def read_file(self, path):
        """Read and return bytes for the given relative path."""
        self.ensure_one()
        with self.open(path, 'rb') as f:
            return f.read()

    def write_file(self, path, data):
        """Write bytes to the given relative path."""
        self.ensure_one()
        with self.open(path, 'wb') as f:
            f.write(data)

    def file_exists(self, path):
        """Return True if the file at the relative path exists."""
        self.ensure_one()
        full = self._full_path(path)
        opts = self._get_options()
        fs, fs_path = fsspec.url_to_fs(full, **opts)
        return fs.exists(fs_path)

    def ls(self, path=''):
        """List files under the given relative path."""
        self.ensure_one()
        full = self._full_path(path)
        opts = self._get_options()
        fs, fs_path = fsspec.url_to_fs(full, **opts)
        return fs.ls(fs_path)

    def action_test_connection(self):
        self.ensure_one()
        try:
            full = self._full_path('')
            opts = self._get_options()
            fs, fs_path = fsspec.url_to_fs(full, **opts)
            fs.ls(fs_path)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': _('Successfully connected to "%s".') % full,
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            _logger.warning('Storage connection test failed for %s: %s', self.name, e)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Failed'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                },
            }
