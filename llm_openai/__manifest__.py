{
    "name": "OpenAI LLM Integration",
    "summary": "OpenAI provider integration for LLM module",
    "description": """
        Implements OpenAI provider service for the LLM integration module.
        Supports GPT models for chat and embedding capabilities.
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Technical",
    "version": "19.0.1.5.0",
    "depends": ["llm"],
    "external_dependencies": {
        "python": ["openai"],
    },
    "data": [
        "data/llm_publisher.xml",
    ],
    "demo": ["data/llm_provider_demo.xml"],
    "images": [
        "static/description/banner.jpeg",
    ],
    "license": "LGPL-3",
    "installable": True,
}
