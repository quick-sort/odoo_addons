import json
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.infohub_channel_mcp.components.fetch import (
    _as_document,
    _as_items,
)


@tagged("post_install", "-at_install")
class TestResultNormalisation(TransactionCase):
    """Tool replies are opaque, so normalisation must never raise."""

    def test_document_unwraps_result_key(self):
        payload = {"result": json.dumps([{"title": "A"}])}
        self.assertEqual(_as_document(payload), [{"title": "A"}])

    def test_document_decodes_json_string(self):
        self.assertEqual(_as_document('{"items": []}'), {"items": []})

    def test_document_passes_through_structures(self):
        self.assertEqual(_as_document([1, 2]), [1, 2])

    def test_non_json_text_is_ignored(self):
        """A prose reply yields nothing rather than blowing up."""
        self.assertIsNone(_as_document("Sorry, I could not find anything."))

    def test_none_stays_none(self):
        self.assertIsNone(_as_document(None))

    def test_items_accepts_bare_list(self):
        self.assertEqual(_as_items([{"a": 1}]), [{"a": 1}])

    def test_items_unwraps_common_envelope_keys(self):
        for key in ("records", "items", "data", "results", "news", "list", "entries"):
            with self.subTest(key=key):
                self.assertEqual(_as_items({key: [{"a": 1}]}), [{"a": 1}])

    def test_items_unknown_shape_yields_empty(self):
        self.assertEqual(_as_items({"unexpected": "shape"}), [])
        self.assertEqual(_as_items({"items": "not-a-list"}), [])

    def test_items_none_yields_empty(self):
        self.assertEqual(_as_items(None), [])


@tagged("post_install", "-at_install")
class TestMcpChannel(TransactionCase):
    """The channel end-to-end, with the MCP client stubbed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["infohub.channel"]
        cls.client = cls.env["llm.mcp.client"].create(
            {
                "name": "Test MCP Server",
                "url": "https://mcp.example.com/mcp",
            }
        )

    def _channel(self, tool="search_news", **vals):
        return self.Channel.create(
            {
                "name": "MCP Feed",
                "channel_type": "mcp",
                "mcp_client_id": self.client.id,
                "mcp_tool_name": tool,
                **vals,
            }
        )

    def _stub_call(self, result):
        return mock.patch.object(
            type(self.client), "call_tool", return_value={"result": result}
        )

    # -- model -----------------------------------------------------------

    def test_mcp_is_a_selectable_channel_type(self):
        selection = dict(self.Channel._fields["channel_type"].selection)
        self.assertIn("mcp", selection)

    def test_channel_without_client_is_rejected_at_fetch(self):
        channel = self.Channel.create(
            {"name": "No client", "channel_type": "mcp", "mcp_tool_name": "t"}
        )
        with self.assertRaises(UserError):
            channel.fetch_news()

    def test_channel_without_tool_name_is_rejected_at_fetch(self):
        channel = self.Channel.create(
            {"name": "No tool", "channel_type": "mcp", "mcp_client_id": self.client.id}
        )
        with self.assertRaises(UserError):
            channel.fetch_news()

    # -- fetching --------------------------------------------------------

    def test_fetch_ingests_items(self):
        channel = self._channel()
        payload = json.dumps(
            [
                {
                    "title": "Drug approved",
                    "url": "https://example.com/n1",
                    "summary": "A summary",
                    "publishedDate": "2026-09-01",
                    "source": "Example News",
                }
            ]
        )
        with self._stub_call(payload):
            channel.action_fetch()

        item = self.env["infohub.item"].search([("channel_id", "=", channel.id)])
        self.assertEqual(len(item), 1)
        self.assertEqual(item.title, "Drug approved")
        self.assertEqual(item.url, "https://example.com/n1")
        self.assertEqual(str(item.published_at.date()), "2026-09-01")
        self.assertIn("A summary", item.content_text)

    def test_envelope_key_is_handled(self):
        channel = self._channel()
        payload = json.dumps({"records": [{"title": "Wrapped", "url": "https://x/1"}]})
        with self._stub_call(payload):
            channel.action_fetch()
        self.assertEqual(
            self.env["infohub.item"].search_count([("channel_id", "=", channel.id)]), 1
        )

    def test_every_tool_field_is_preserved_for_filtering(self):
        """filter_domain matches raw_data, so nothing may be dropped."""
        channel = self._channel(filter_domain=[["NEWSTYPE", "=", "regulatory"]])
        payload = json.dumps(
            [
                {"title": "Kept", "NEWSTYPE": "regulatory"},
                {"title": "Dropped", "NEWSTYPE": "marketing"},
            ]
        )
        with self._stub_call(payload):
            channel.action_fetch()

        items = self.env["infohub.item"].search([("channel_id", "=", channel.id)])
        self.assertEqual(len(items), 1)
        self.assertEqual(items.title, "Kept")
        self.assertEqual(items.raw_data["NEWSTYPE"], "regulatory")

    def test_unparseable_reply_creates_nothing(self):
        """A prose reply is not an error, it is simply empty."""
        channel = self._channel()
        with self._stub_call("No news found today, sorry."):
            channel.action_fetch()
        self.assertEqual(channel.item_count, 0)

    def test_refetch_does_not_duplicate(self):
        channel = self._channel()
        payload = json.dumps([{"title": "Once", "url": "https://example.com/same"}])
        with self._stub_call(payload):
            channel.action_fetch()
            channel.action_fetch()
        self.assertEqual(channel.item_count, 1)

    def test_date_range_is_passed_to_the_tool(self):
        """The channel forwards its fetch window to the tool."""
        channel = self._channel()
        import datetime

        with mock.patch.object(
            type(self.client), "call_tool", return_value={"result": "[]"}
        ) as call:
            channel.fetch_news(
                date_from=datetime.date(2026, 9, 1),
                date_to=datetime.date(2026, 9, 30),
            )
        arguments = call.call_args[0][1]
        self.assertEqual(arguments.get("dateFrom"), "2026-09-01")
        self.assertEqual(arguments.get("dateTo"), "2026-09-30")

    def test_llm_dependency_is_isolated_to_this_addon(self):
        """The core must stay free of llm even with every channel installed."""
        core_deps = (
            self.env["ir.module.module"]
            .search([("name", "=", "infohub")])
            .dependencies_id.mapped("name")
        )
        self.assertNotIn("llm", core_deps)
