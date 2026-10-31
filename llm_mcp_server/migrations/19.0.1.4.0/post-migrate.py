def migrate(cr, installed_version):
    if not installed_version:
        return

    # ``expose_to_mcp`` is new; ``_auto_init`` backfilled every existing row to
    # true. Remote tools are imported for Odoo's own LLM agents, not for
    # re-publication, so flip them back off to match the create() default.
    cr.execute("UPDATE llm_tool SET expose_to_mcp = false WHERE source = 'remote'")
