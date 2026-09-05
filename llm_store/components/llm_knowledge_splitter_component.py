"""Base class for llm.knowledge.splitter components."""

from odoo.addons.component.core import AbstractComponent


class LLMKnowledgeSplitterComponent(AbstractComponent):
    _name = "llm.knowledge.splitter.component"
    _collection = "llm.knowledge.splitter"

    def split(self, text, **context):
        """Split ``text`` into a list of chunk strings.

        ``context`` may carry extra information some splitters use, e.g.
        the 'contextual' splitter expects ``resource`` (the llm.resource
        being split) so it can build a document-level context prefix.
        """
        raise NotImplementedError
