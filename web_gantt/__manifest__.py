# -*- coding: utf-8 -*-
{
    "name": "Gantt View",
    "summary": "Generic Gantt chart view",
    "version": "19.0.0.0.0",
    "category": "Productivity",
    "author": "Concept Solutions LLC",
    "website": "https://www.csloman.com",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "web_gantt/static/src/scss/gantt_view.scss",
            "web_gantt/static/src/js/gantt_renderer.js",
            "web_gantt/static/src/js/gantt_view.js",
            "web_gantt/static/src/xml/gantt_view.xml",
        ],
    },
    "installable": True,
}
