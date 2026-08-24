{
    'name': 'Conference Posters',
    'version': '19.0.1.0.0',
    'category': 'Medical',
    'summary': 'Index and manage conference poster documents (PDF, PPTX, TXT)',
    'images': ['static/description/icon.png'],
    'depends': ['base', 'web_json_editor'],
    'external_dependencies': {'python': ['fsspec', 's3fs']},
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/poster_storage_views.xml',
        'views/conference_poster_views.xml',
        'views/conference_conference_views.xml',
        'views/menus.xml',
        'data/poster_server_actions.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'posters/static/src/js/poster_preview.js',
        ],
    },
    'demo': [
        'demo/demo_data.xml',
    ],
    'author': 'Rui Zhou',
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
