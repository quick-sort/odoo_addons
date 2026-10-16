{
    "name": "Project Task DAG",
    "summary": "Visualize project task dependencies as a directed graph",
    "version": "19.0.1.0.0",
    "category": "Project",
    "author": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "depends": ["project", "web"],
    "data": [
        "views/project_task_views.xml",
    ],
    "demo": [
        "demo/task_dependency_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "project_task_dag/static/src/dependency_graph/dependency_graph.js",
            "project_task_dag/static/src/dependency_graph/dependency_graph.xml",
            "project_task_dag/static/src/dependency_graph/dependency_graph.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
