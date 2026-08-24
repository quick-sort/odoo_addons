import logging
import os

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ConferencePoster(models.Model):
    _name = 'conference.poster'
    _description = 'Conference Poster'
    _order = 'conference_id, abstract_no, name'

    def _auto_init(self):
        super()._auto_init()
        try:
            self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        except Exception:
            self.env.cr.rollback()
            _logger.warning("pg_trgm extension not available, trigram indexes skipped")
            return
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS conference_poster_name_trgm_idx
            ON conference_poster USING gin(name gin_trgm_ops)
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS conference_poster_abstract_no_trgm_idx
            ON conference_poster USING gin(abstract_no gin_trgm_ops)
        """)

    name = fields.Char(string='Title', required=True)
    abstract_no = fields.Char(string='Abstract No')
    conference_id = fields.Many2one('conference.conference', string='Collection', index=True)
    category = fields.Char(string='Category')
    indication_ids = fields.Many2many(
        'conference.indication',
        'conference_poster_indication_rel',
        'poster_id',
        'indication_id',
        string='Indications',
    )
    target_ids = fields.Many2many(
        'conference.target',
        'conference_poster_target_rel',
        'poster_id',
        'target_id',
        string='Targets',
    )
    phase = fields.Selection(
        [
            ('preclinical', 'Preclinical'),
            ('phase_1', 'Phase I'),
            ('phase_2', 'Phase II'),
            ('phase_3', 'Phase III'),
            ('phase_4', 'Phase IV'),
        ],
        string='Phase',
        index=True,
    )
    file_path = fields.Char(
        string='File Path',
        required=True,
        help='Filename (or relative path) within the collection path, e.g. abstract123.pdf',
    )
    file_name = fields.Char(compute='_compute_file_info', store=True)
    file_type = fields.Selection(
        [
            ('pdf', 'PDF'),
            ('pptx', 'PowerPoint'),
            ('txt', 'Text'),
            ('mp4', 'MP4 Video'),
            ('webm', 'WebM Video'),
            ('mkv', 'MKV Video'),
            ('png', 'PNG'),
            ('jpg', 'JPEG'),
            ('gif', 'GIF'),
        ],
        compute='_compute_file_info',
        store=True,
    )

    @api.depends('file_path')
    def _compute_file_info(self):
        known = {'pdf', 'pptx', 'txt', 'mp4', 'webm', 'mkv', 'png', 'jpg', 'jpeg', 'gif'}
        for rec in self:
            if rec.file_path:
                rec.file_name = os.path.basename(rec.file_path)
                ext = os.path.splitext(rec.file_path)[1].lower().lstrip('.')
                if ext == 'jpeg':
                    ext = 'jpg'
                rec.file_type = ext if ext in known else False
            else:
                rec.file_name = False
                rec.file_type = False

    def action_preview(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'poster_preview_action',
            'params': {
                'poster_id': self.id,
                'title': self.name,
                'file_type': self.file_type,
                'mime_type': self._file_mime_type(),
            },
        }

    def _file_mime_type(self):
        self.ensure_one()
        return {
            'pdf': 'application/pdf',
            'txt': 'text/plain',
            'mp4': 'video/mp4',
            'webm': 'video/webm',
            'mkv': 'video/x-matroska',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'gif': 'image/gif',
        }.get(self.file_type or '', 'application/octet-stream')

    def action_download_single(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/poster/download/{self.id}',
            'target': 'new',
        }

    def action_download_zip(self):
        ids = ','.join(str(r.id) for r in self)
        return {
            'type': 'ir.actions.act_url',
            'url': f'/poster/download/zip?ids={ids}',
            'target': 'new',
        }
