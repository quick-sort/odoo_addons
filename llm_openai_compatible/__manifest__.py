{
    "name": "OpenAI-Compatible LLM Integration",
    "summary": "Chat-completions-protocol image output for OpenAI-compatible endpoints",
    "description": """
        Extends the OpenAI service adapter for third-party endpoints that speak
        the OpenAI chat-completions wire format but return generated images
        inline in the chat response -- a vendor extension the official OpenAI
        API does not have (litellm, Gemini via the chat-completions shim,
        local servers...).

        Kept out of ``llm_openai``, which implements the official protocol
        only: the official Chat Completions API never returns images, image
        generation is a separate endpoint (``images.generate``).

        Install this alongside ``llm_openai`` and pick the 'OpenAI Compatible'
        service on the provider record when pointing ``api_base`` at one of
        these endpoints.
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Technical",
    "version": "19.0.1.0.0",
    "depends": ["llm_openai"],
    "external_dependencies": {
        "python": ["openai"],
    },
    "data": [],
    "license": "LGPL-3",
    "installable": True,
}
