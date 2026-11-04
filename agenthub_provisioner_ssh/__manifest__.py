{
    "name": "Agent Hub Provisioner (SSH)",
    "summary": "SSH driver for agenthub_provisioner",
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": ["agenthub_provisioner"],
    "external_dependencies": {"python": ["paramiko"]},
    "data": [
        "views/agenthub_provisioner_host_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
