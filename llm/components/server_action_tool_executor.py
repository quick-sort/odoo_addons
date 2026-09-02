"""``server_action`` executor: run an ``ir.actions.server``.

Arguments arrive in the context key ``llm_tool_params``, since
``ir.actions.server.run()`` takes no arguments -- the action's own code has to
read ``env.context['llm_tool_params']``. Nothing can check that the action
actually reads the keys the schema advertises, which is why this executor is
the least safe of the three.
"""

from odoo import _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.component.core import Component


class ServerActionToolExecutor(Component):
    _name = "server_action.tool.executor"
    _inherit = "llm.tool.executor"
    _usage = "server_action"

    def execute(self, params):
        tool = self.collection
        tool.ensure_one()
        if not tool.server_action_id:
            raise UserError(
                _("Tool '%(name)s' has no server action configured.", name=tool.name)
            )
        return tool.server_action_id.with_context(llm_tool_params=params).run()

    def validate(self, tool):
        if not tool.server_action_id:
            raise ValidationError(
                _(
                    "Tool '%(name)s' uses the Server Action executor, which "
                    "needs a server action.",
                    name=tool.name,
                )
            )
