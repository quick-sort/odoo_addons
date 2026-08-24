import csv
import io
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ConferenceConference(models.Model):
    _name = 'conference.conference'
    _description = 'Collection'
    _order = 'date desc, name'

    name = fields.Char(required=True)
    date = fields.Date()
    location = fields.Char()
    storage_id = fields.Many2one('poster.storage', string='Storage')
    path = fields.Char(
        string='Path',
        help='Path within the storage for this collection, e.g. 2024/asco',
    )
    poster_ids = fields.One2many('conference.poster', 'conference_id', string='Posters')
    poster_count = fields.Integer(compute='_compute_poster_count')

    def _compute_poster_count(self):
        counts = self.env['conference.poster']._read_group(
            [('conference_id', 'in', self.ids)],
            ['conference_id'],
            ['__count'],
        )
        count_map = {conf.id: count for conf, count in counts}
        for rec in self:
            rec.poster_count = count_map.get(rec.id, 0)

    def _poster_file_path(self, filename):
        """Return the full relative path for a poster file within this collection."""
        self.ensure_one()
        base = (self.path or '').strip('/')
        name = (filename or '').lstrip('/')
        return f'{base}/{name}' if base else name

    def action_import_metadata(self):
        self.ensure_one()
        if not self.storage_id:
            raise UserError(_('This collection has no storage configured.'))

        metadata_path = self._poster_file_path('metadata.csv')
        try:
            raw = self.storage_id.read_file(metadata_path)
        except Exception as e:
            raise UserError(_('Could not read metadata.csv: %s') % e) from e

        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        Poster = self.env['conference.poster']
        created = updated = 0

        for row in reader:
            file_name = (row.get('file') or '').strip()
            title = (row.get('title') or '').strip()
            category = (row.get('category') or '').strip()
            if not file_name:
                continue

            existing = Poster.search(
                [('conference_id', '=', self.id), ('file_path', '=', file_name)],
                limit=1,
            )
            vals = {
                'name': title or file_name,
                'file_path': file_name,
                'category': category,
            }
            if existing:
                existing.write(vals)
                updated += 1
            else:
                vals['conference_id'] = self.id
                Poster.create(vals)
                created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Complete'),
                'message': _('%d created, %d updated.') % (created, updated),
                'type': 'success',
                'sticky': False,
            },
        }
