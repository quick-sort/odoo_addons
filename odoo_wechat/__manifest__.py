# -*- coding: utf-8 -*-
{
    'name': "企业微信",
    'summary': """企业微信自建应用管理：CorpID配置、企微应用(AgentID/Secret)、应用消息/H5发布""",
    'description': """ """,
    'author': "XueFeng.Su",
    'website': "https://github.com/cd-feng",
    'category': 'Wechat',
    'version': '19.0.1.0',
    'depends': ['base', 'web'],
    "license": "AGPL-3",
    'installable': True,
    'application': True,
    'auto_install': False,
    'external_dependencies': {
        'python': ['wechatpy']
    },
    'data': [
        'security/ir.model.access.csv',

        'views/wechat_app_views.xml',
        'views/wechat_app_message_views.xml',
        'views/wechat_app_message_templates.xml',
        'views/wechat_contacts_views.xml',
        'views/menu.xml',
    ],
    'images': [
        'static/description/setting_img.png',
        'static/description/setting_img2.png'
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_wechat/static/src/fields/wechat_html_preview_field.js',
            'odoo_wechat/static/src/fields/wechat_html_preview_field.xml',
        ],
    },
}
