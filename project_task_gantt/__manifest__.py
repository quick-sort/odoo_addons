# -*- coding: utf-8 -*-
{
    "name": "Project Task Gantt",
    "summary": "Gantt chart view for project tasks",
    "version": "19.0.0.0.0",
    "category": "Productivity",
    "author": "Concept Solutions LLC",
    "website": "https://www.csloman.com",
    "license": "LGPL-3",
    "depends": ["project", "web_gantt"],
    "data": [
        "security/ir.model.access.csv",
        "views/project_task_views.xml",
        "views/project_task_gantt_views.xml",
    ],
    "installable": True,
}
