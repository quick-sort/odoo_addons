{
    "name": "Project Task Plan",
    "summary": "Auto-schedule project tasks based on dependencies",
    "version": "19.0.1.0.0",
    "category": "Project",
    "author": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "depends": ["project", "project_task_gantt"],
    "data": [
        "security/ir.model.access.csv",
        "views/project_project_views.xml",
        "views/project_task_views.xml",
        "views/project_task_plan_result_views.xml",
    ],
    "installable": True,
    "application": False,
}
