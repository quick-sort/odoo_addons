{
    "name": "LLM Integration Base",
    "summary": """
        Integration with various LLM providers like Ollama, OpenAI, Replicate and Anthropic""",
    "description": """
        Provides integration with LLM (Large Language Model) providers for:
        - Chat completions
        - Text embeddings
        - Model management
        - Function calling / tool execution (built-in Odoo CRUD tools, custom
          model methods, server actions, and remote MCP servers)
        - Real-time AI chat threads, linked to any Odoo record
        - Configurable AI assistants with prompt templates, categories, tags
          and preferred tools

    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity, Discuss",
    "version": "19.0.1.8.0",
    "depends": ["mail", "web", "component", "web_json_editor"],
    "external_dependencies": {
        "python": [
            "pydantic>=2.0.0",
            "mcp",
            "requests",
            "emoji",
            "markdown2",
            "jinja2",
            "pyyaml",
            "jsonschema",
        ],
    },
    "data": [
        "security/llm_security.xml",
        "security/ir.model.access.csv",
        "security/llm_thread_security.xml",
        "wizards/fetch_models_views.xml",
        "views/llm_provider_views.xml",
        "views/llm_model_views.xml",
        "views/llm_publisher_views.xml",
        "views/llm_tool_views.xml",
        "views/llm_tool_consent_config_views.xml",
        "views/llm_mcp_client_views.xml",
        "views/llm_thread_views.xml",
        "views/llm_assistant_tag_views.xml",
        "views/llm_assistant_category_views.xml",
        "views/llm_assistant_views.xml",
        "views/llm_menu_views.xml",
        "data/mail_message_subtype.xml",
        "data/llm_tool_data.xml",
        "data/llm_tool_consent_config_data.xml",
        "data/llm_tool_server_actions.xml",
        "data/llm_assistant_tag_data.xml",
        "data/llm_assistant_category_data.xml",
        "data/llm_tool_invoke_assistant_data.xml",
        "data/llm_assistant_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # Services - LLM store service for integration with mail.store
            "llm/static/src/services/llm_store_service.js",
            "llm/static/src/services/llm_store_service_assistant_patch.js",
            # Components - LLM Chat Container using existing mail components
            "llm/static/src/components/llm_chat_container/llm_chat_container.js",
            "llm/static/src/components/llm_chat_container/llm_chat_container.xml",
            "llm/static/src/components/llm_chat_container/llm_chat_container.scss",
            # Thread Header component with provider/model/tool selections
            "llm/static/src/components/llm_thread_header/llm_thread_header.js",
            "llm/static/src/components/llm_thread_header/llm_thread_header.xml",
            "llm/static/src/components/llm_thread_header/llm_thread_header.scss",
            # Related Record component for linking threads to Odoo records
            "llm/static/src/components/llm_related_record/llm_related_record.js",
            "llm/static/src/components/llm_related_record/llm_related_record.xml",
            "llm/static/src/components/llm_related_record/llm_related_record.scss",
            "llm/static/src/components/llm_related_record/llm_record_picker_dialog.js",
            "llm/static/src/components/llm_related_record/llm_record_picker_dialog.xml",
            # Tool Message component for displaying tool results
            "llm/static/src/components/llm_tool_message/llm_tool_message.js",
            "llm/static/src/components/llm_tool_message/llm_tool_message.xml",
            "llm/static/src/components/llm_tool_message/llm_tool_message.scss",
            # Patches - Safe extensions of mail components with conditional LLM logic
            "llm/static/src/patches/composer_patch.js",
            "llm/static/src/patches/composer_patch.xml",
            "llm/static/src/patches/thread_patch.js",
            "llm/static/src/patches/thread_model_patch.js",
            "llm/static/src/patches/chatter_patch.js",
            "llm/static/src/patches/message_patch.js",
            "llm/static/src/patches/message_patch.xml",
            # Assistant selector patch on the thread header
            "llm/static/src/patches/llm_thread_header_assistant_patch.js",
            "llm/static/src/patches/llm_thread_header_assistant_patch.xml",
            # Templates - Extensions of existing mail templates
            "llm/static/src/templates/chatter_ai_button.xml",
            "llm/static/src/templates/llm_chat_client_action.xml",
            # Client Actions
            "llm/static/src/client_actions/llm_chat_client_action.js",
            "llm/static/src/client_actions/open_chatter_action.js",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
    "images": [
        "static/description/banner.jpeg",
    ],
}
