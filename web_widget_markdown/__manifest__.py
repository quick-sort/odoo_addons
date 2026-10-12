# -*- coding: utf-8 -*-
{
    "name": "Web Widget Markdown",
    "summary": "Markdown field widget with a source textarea and a rendered preview",
    "version": "19.0.1.0.0",
    "category": "Web",
    "license": "LGPL-3",
    "author": "quick-sort@outlook.com",
    "depends": ["web"],
    "data": [],
    "assets": {
        "web_widget_markdown.assets_lib": [
            "web_widget_markdown/static/lib/marked/marked.min.js",
        ],
        "web.assets_backend": [
            "web_widget_markdown/static/src/fields/markdown/**/*.js",
            "web_widget_markdown/static/src/fields/markdown/**/*.xml",
            "web_widget_markdown/static/src/fields/markdown/**/*.scss",
        ],
    },
}
