# -*- coding: utf-8 -*-
{
    "name": "Web Widget Mermaid",
    "summary": "Render a (computed) text field as a Mermaid diagram",
    "description": (
        "Provides a `mermaid` field widget that feeds the field's content "
        "(typically a computed Text/Char field) to the Mermaid.js library "
        "and renders the resulting diagram inline. Read-only by default; "
        "falls back to a plain textarea in edit mode."
    ),
    "version": "19.0.1.0.0",
    "category": "Productivity",
    "website": "https://mermaid.js.org/",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web_widget_mermaid.assets_lib": [
            "web_widget_mermaid/static/lib/mermaid/mermaid.min.js",
        ],
        "web.assets_backend": [
            "web_widget_mermaid/static/src/fields/mermaid/**/*.js",
            "web_widget_mermaid/static/src/fields/mermaid/**/*.xml",
            "web_widget_mermaid/static/src/fields/mermaid/**/*.scss",
        ],
    },
}
