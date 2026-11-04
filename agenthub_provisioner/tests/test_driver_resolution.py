from odoo.exceptions import UserError
from odoo.tests import common, tagged

from odoo.addons.agenthub.tests.common import selection_value
from odoo.addons.agenthub_provisioner.components.driver import (
    AgenthubProvisionerDriver,
)
from odoo.addons.agenthub_provisioner.contract import HostProbe
from odoo.addons.component.core import Component
from odoo.addons.component.tests.common import TransactionComponentRegistryCase


class TestDriver(Component):
    _name = "agenthub.provisioner.driver.test"
    _inherit = "agenthub.provisioner.driver"
    _usage = "test"

    def probe(self, host):
        return HostProbe(True, "test-1.0")


class BareDriver(Component):
    _name = "agenthub.provisioner.driver.bare"
    _inherit = "agenthub.provisioner.driver"
    _usage = "bare"


@tagged("post_install", "-at_install")
class TestDriverResolution(TransactionComponentRegistryCase, common.TransactionCase):
    def setUp(self):
        super().setUp()
        self._setup_registry(self)
        self.addCleanup(self._teardown_registry, self)
        self._build_components(
            AgenthubProvisionerDriver, TestDriver, BareDriver
        )
        self.env = self.env(
            context=dict(
                self.env.context, components_registry=self.comp_registry
            )
        )
        self._enter_selection("test")
        self._enter_selection("bare")
        self._enter_selection("missing")

    def _enter_selection(self, value):
        manager = selection_value(
            self.env["agenthub.provisioner.host"],
            "driver_type",
            value,
            value.title(),
        )
        manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)

    def _host(self, driver_type):
        return self.env["agenthub.provisioner.host"].create(
            {"name": "Host %s" % driver_type, "driver_type": driver_type}
        )

    def test_resolves_by_usage(self):
        host = self._host("test")
        self.assertIsInstance(host._driver(), TestDriver)

    def test_two_usages_do_not_conflict(self):
        test_driver = self._host("test")._driver()
        bare_driver = self._host("bare")._driver()
        self.assertIsInstance(test_driver, TestDriver)
        self.assertIsInstance(bare_driver, BareDriver)
        self.assertNotEqual(type(test_driver), type(bare_driver))

    def test_missing_driver_raises_user_error(self):
        host = self._host("missing")
        with self.assertRaises(UserError):
            host._driver()

    def test_abstract_methods_raise_not_implemented(self):
        host = self._host("bare")
        with self.assertRaises(NotImplementedError):
            host._driver().probe(host)
