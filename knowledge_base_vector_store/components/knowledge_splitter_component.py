# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Base class for knowledge splitter components."""

from odoo.addons.component.core import AbstractComponent


class KnowledgeSplitterComponent(AbstractComponent):
    _name = "knowledge.splitter.component"
    _collection = "knowledge.splitter"

    def split(self, text):
        """Split ``text`` into a list of chunk strings."""
        raise NotImplementedError
