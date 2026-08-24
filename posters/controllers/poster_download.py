import io
import logging
import os
import zipfile

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

CONTENT_TYPES = {
    'pdf': 'application/pdf',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'txt': 'text/plain; charset=utf-8',
    'mp4': 'video/mp4',
    'webm': 'video/webm',
    'mkv': 'video/x-matroska',
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'gif': 'image/gif',
}


def _read_poster_file(poster):
    """Return raw bytes for a poster using its collection's storage."""
    conference = poster.conference_id
    storage = conference.storage_id
    if not storage:
        raise FileNotFoundError(f'Collection "{conference.name}" has no storage configured')
    full_path = conference._poster_file_path(poster.file_path)
    return storage.read_file(full_path)


class PosterDownloadController(http.Controller):

    @http.route('/poster/download/<int:poster_id>', type='http', auth='user')
    def download_single(self, poster_id, **kwargs):
        poster = request.env['conference.poster'].browse(poster_id)
        if not poster.exists():
            return request.not_found()

        try:
            data = _read_poster_file(poster)
        except Exception as e:
            _logger.error('Failed to read poster %s: %s', poster_id, e)
            return request.not_found()

        content_type = CONTENT_TYPES.get(poster.file_type, 'application/octet-stream')
        filename = poster.file_name or os.path.basename(poster.file_path)
        return request.make_response(
            data,
            headers=[
                ('Content-Type', content_type),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
                ('Content-Length', str(len(data))),
            ],
        )

    @http.route('/poster/preview/<int:poster_id>', type='http', auth='user')
    def preview_single(self, poster_id, **kwargs):
        poster = request.env['conference.poster'].browse(poster_id)
        if not poster.exists() or poster.file_type not in ('pdf', 'txt', 'mp4', 'webm', 'mkv', 'png', 'jpg', 'gif'):
            return request.not_found()

        try:
            data = _read_poster_file(poster)
        except Exception as e:
            _logger.error('Failed to read poster %s for preview: %s', poster_id, e)
            return request.not_found()

        content_type = CONTENT_TYPES.get(poster.file_type, 'application/octet-stream')
        filename = poster.file_name or os.path.basename(poster.file_path)
        return request.make_response(
            data,
            headers=[
                ('Content-Type', content_type),
                ('Content-Disposition', f'inline; filename="{filename}"'),
                ('Content-Length', str(len(data))),
            ],
        )

    @http.route('/poster/download/zip', type='http', auth='user', methods=['GET', 'POST'])
    def download_zip(self, ids='', **kwargs):
        try:
            poster_ids = [int(i) for i in ids.split(',') if i.strip()]
        except ValueError:
            return request.not_found()

        posters = request.env['conference.poster'].browse(poster_ids)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            seen_names = {}
            for poster in posters:
                filename = poster.file_name or os.path.basename(poster.file_path)
                if filename in seen_names:
                    seen_names[filename] += 1
                    base, ext = os.path.splitext(filename)
                    filename = f'{base}_{seen_names[filename]}{ext}'
                else:
                    seen_names[filename] = 0

                try:
                    data = _read_poster_file(poster)
                    zf.writestr(filename, data)
                except Exception as e:
                    _logger.error('Skipping poster %s in zip: %s', poster.id, e)

        buf.seek(0)
        return request.make_response(
            buf.read(),
            headers=[
                ('Content-Type', 'application/zip'),
                ('Content-Disposition', 'attachment; filename="posters.zip"'),
            ],
        )
