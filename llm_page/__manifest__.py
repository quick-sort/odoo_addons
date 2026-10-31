{
    "name": "LLM Page",
    "version": "19.0.1.1.0",
    "category": "Website",
    "summary": "Host agent-generated static HTML pages on the website with a review workflow and group-based access",
    "author": "quick-sort@outlook.com",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "website",
        "llm",
    ],
    "external_dependencies": {},
    "data": [
        "security/llm_page_security.xml",
        "security/ir.model.access.csv",
        "views/llm_page_templates.xml",
        "views/llm_page_views.xml",
    ],
    "demo": [],
    "application": False,
    "auto_install": False,
}
