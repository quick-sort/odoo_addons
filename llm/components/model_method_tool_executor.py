"""``model_method`` executor: ``env[res_model][.browse(res_id)].res_method(**params)``.

The default executor, and the one ``source='code'`` tools always use: the
callable behind a ``@llm_tool`` decorated method is resolved here too, since
its signature is what the schema is derived from.
"""

from odoo import _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.component.core import Component


class ModelMethodToolExecutor(Component):
    _name = "model_method.tool.executor"
    _inherit = "llm.tool.executor"
    _usage = "model_method"

    def execute(self, params):
        tool = self.collection
        return self.resolve_callable(tool)(**params)

    def validate(self, tool):
        if not (tool.res_model and tool.res_method):
            raise ValidationError(
                _(
                    "Tool '%(name)s' uses the Model Method executor, which "
                    "needs both a model and a method.",
                    name=tool.name,
                )
            )

    def resolve_callable(self, tool):
        """Return the bound callable for a ``model_method`` tool.

        Bound, not unbound: :func:`odoo.addons.llm.models.llm_tool.derive_input_schema`
        must not see ``self``.
        """
        tool.ensure_one()

        if not tool.res_model or not tool.res_method:
            raise UserError(
                _(
                    "Tool '%(name)s' has no model/method configured.",
                    name=tool.name,
                )
            )
        if tool.res_model not in tool.env:
            raise UserError(
                _(
                    "Model '%(model)s' of tool '%(name)s' does not exist. Is the "
                    "addon providing it installed?",
                    model=tool.res_model,
                    name=tool.name,
                )
            )

        target = tool.env[tool.res_model]
        if tool.res_id:
            target = target.browse(tool.res_id)
            if not target.exists():
                raise UserError(
                    _(
                        "Record %(id)s of %(model)s, bound to tool '%(name)s', "
                        "no longer exists.",
                        id=tool.res_id,
                        model=tool.res_model,
                        name=tool.name,
                    )
                )

        if not hasattr(target, tool.res_method):
            raise UserError(
                _(
                    "Method '%(method)s' not found on %(model)s for tool "
                    "'%(name)s'.",
                    method=tool.res_method,
                    model=tool.res_model,
                    name=tool.name,
                )
            )

        return getattr(target, tool.res_method)
