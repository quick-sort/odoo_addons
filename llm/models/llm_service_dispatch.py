"""Shared service dispatch for the polymorphic LLM backends.

Several models in this stack are "a configuration record plus a service key,
implemented by one adapter per service":

- ``llm.provider`` (``llm``) -- openai, anthropic, ...
- ``llm.store`` (``llm_store``) -- pgvector, qdrant, ...

They all resolve an adapter component from the value of a selection field and
call plain method names on it. This mixin holds that resolution once.

To use it, a model must:

1. inherit ``collection.base`` (so components can be registered against it)
   and this mixin;
2. carry a selection field named by :attr:`_service_field` whose values are the
   ``_usage`` of the adapter components. Declare it with a static ``selection``
   list and let other addons extend it with ``selection_add`` -- not with a
   dynamic ``selection=lambda``, which Odoo does not validate on write at all
   (``Selection._selection`` stays ``None``, so ``convert_to_cache`` skips the
   membership check and a typo is stored silently);
3. ship an abstract base component with ``_collection`` set to the model name,
   which scopes component lookups to that collection.

An addon contributing a service therefore declares two things: the adapter
component, and a ``selection_add`` entry with an ``ondelete`` policy -- use
:func:`archive_dangling_service` unless there is a reason not to.
"""

from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.component.exception import NoComponentError, RegistryNotReadyError


def archive_dangling_service(records):
    """``ondelete`` policy for service/implementation selection values.

    Runs when the addon that contributed a value is uninstalled, on the records
    still holding it. Archives them instead of deleting them.

    ``cascade`` is the obvious alternative and is wrong here. ``llm.provider``
    rows carry API keys and ``llm.model.provider_id`` is itself
    ``ondelete="cascade"``, so uninstalling ``llm_openai`` would silently
    destroy every OpenAI provider *and* all its models -- a large, irreversible
    blast radius for a module uninstall. ``set null`` is rejected by Odoo on
    required fields, and ``set default`` needs a default these fields cannot
    have.

    Archiving keeps the configuration intact and out of the way: reinstall the
    addon, unarchive, and it works again. The stale value stays in the column,
    which is harmless -- :meth:`LLMServiceDispatchMixin._dispatch` already
    reports it as "no adapter registered, is the addon installed?".
    """
    if records:
        records.write({"active": False})


class LLMServiceDispatchMixin(models.AbstractModel):
    _name = "llm.service.dispatch.mixin"
    _description = "LLM Service Dispatch Mixin"

    #: Field holding the service key, matched against component ``_usage``.
    _service_field = "service"

    #: Whether :meth:`_dispatch` passes the record as the adapter's first
    #: positional argument.
    #:
    #: True for ``llm.provider`` and ``llm.store``: an adapter that receives
    #: its record explicitly can be unit-tested without a database.
    #:
    #: ``llm.tool`` sets it False, because there the adapter method signature
    #: is *itself* the JSON Schema advertised to the LLM -- an extra leading
    #: parameter would show up as a tool argument. Those adapters read the
    #: record from ``self.collection`` instead.
    _dispatch_pass_record = True

    def _service_key(self):
        """Return the configured service key, or a falsy value."""
        return self[self._service_field]

    def _get_adapter(self):
        """Return the adapter component for this record's service, or ``None``.

        ``None`` means no adapter is registered for that service, which
        :meth:`_dispatch` turns into a clear ``UserError`` -- normally it means
        the addon providing the service is not installed.

        :exc:`NoComponentError` and :exc:`RegistryNotReadyError` are both
        swallowed. The latter happens when a record is created from an
        addon's own ``data/*.xml`` during module loading (e.g. ``llm.tool``'s
        built-in tools): that runs before ``component.builder._register_hook``
        has built the component registry for this database, since components
        are only wired up after every module's data has loaded. Treating it
        the same as "no adapter yet" is correct here -- optional-contract
        probes (:meth:`_has_service_method`) fall back cleanly, and
        :meth:`_dispatch` itself is never reached that early because nothing
        calls ``execute``/``chat``/... during module loading.

        ``SeveralComponentError`` propagates on purpose: two adapters claiming
        the same ``_usage`` is a deployment mistake, not something to paper
        over.

        Adapter methods are called with the record as their first positional
        argument (unless :attr:`_dispatch_pass_record` is False), so an adapter
        never has to read ``self.collection`` and can be unit-tested without a
        database.

        ``self`` is always a singleton here: :meth:`_dispatch` reads the
        service field before consulting the adapter, and reading a field on a
        multi-record recordset already raises.
        """
        try:
            with self.work_on(self._name) as work:
                return work.component(usage=self._service_key())
        except (NoComponentError, RegistryNotReadyError):
            return None

    def _dispatch(self, method, *args, **kwargs):
        """Dispatch ``method`` to the adapter for this record's service.

        Args:
            method: Contract name (e.g. ``chat``), called on the adapter as
                ``adapter.<method>(self, *args, **kwargs)``, or as
                ``adapter.<method>(*args, **kwargs)`` when
                :attr:`_dispatch_pass_record` is False

        Raises:
            UserError: when no service is configured, or the service has no
                adapter registered
            NotImplementedError: when the adapter does not implement ``method``
            ValueError: when called on a multi-record recordset, since reading
                the service field requires a singleton
        """
        service = self._service_key()
        if not service:
            raise UserError(
                _("Service not configured on %(model)s", model=self._description),
            )

        adapter = self._get_adapter()
        if adapter is None:
            raise UserError(
                _(
                    "No adapter is registered for service '%(service)s'. Is the "
                    "addon providing it installed?",
                    service=service,
                ),
            )

        if not hasattr(adapter, method):
            raise NotImplementedError(
                _(
                    "Method '%(method)s' not implemented by the adapter for "
                    "service '%(service)s'",
                    method=method,
                    service=service,
                ),
            )

        target = getattr(adapter, method)
        if self._dispatch_pass_record:
            return target(self, *args, **kwargs)
        return target(*args, **kwargs)

    def _has_service_method(self, method):
        """Check whether the adapter for this service implements ``method``.

        Lets callers probe optional capabilities without triggering the
        exceptions :meth:`_dispatch` raises.
        """
        if not self._service_key():
            return False

        adapter = self._get_adapter()
        return adapter is not None and hasattr(adapter, method)
