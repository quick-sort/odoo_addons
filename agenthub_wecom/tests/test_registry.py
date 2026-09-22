from odoo.tests import common, tagged

from ..services.aibot import ConnectionRegistry


class FakeConnection:
    def __init__(self):
        self.kicked = False
        self.sent = []

    def kick(self):
        self.kicked = True

    def send(self, frame):
        self.sent.append(frame)


@tagged("post_install", "-at_install")
class TestConnectionRegistry(common.TransactionCase):
    def test_register_and_get(self):
        reg = ConnectionRegistry()
        conn = FakeConnection()
        reg.register("bot1", conn)
        self.assertIs(reg.get("bot1"), conn)

    def test_register_kicks_previous(self):
        reg = ConnectionRegistry()
        first, second = FakeConnection(), FakeConnection()
        reg.register("bot1", first)
        reg.register("bot1", second)
        self.assertTrue(first.kicked)
        self.assertFalse(second.kicked)
        self.assertIs(reg.get("bot1"), second)

    def test_different_bots_do_not_kick(self):
        reg = ConnectionRegistry()
        a, b = FakeConnection(), FakeConnection()
        reg.register("bot1", a)
        reg.register("bot2", b)
        self.assertFalse(a.kicked)
        self.assertFalse(b.kicked)

    def test_unregister_removes_only_matching_connection(self):
        reg = ConnectionRegistry()
        conn = FakeConnection()
        reg.register("bot1", conn)
        reg.unregister("bot1", FakeConnection())  # not the stored one
        self.assertIs(reg.get("bot1"), conn)
        reg.unregister("bot1", conn)
        self.assertIsNone(reg.get("bot1"))
