from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMCPToolTransaction(TransactionCase):
    """A failing tool call must not leave its writes behind.

    ``execute_mcp_tool`` turns whatever the tool raises into an ``isError``
    result instead of letting it propagate to the HTTP layer. That is the right
    response shape, but it also means the transaction is never rolled back:
    without a savepoint around the call, everything the tool flushed before it
    raised stays in the cursor and is committed along with the response.

    The caller then sees "the tool failed" while the database holds a partial
    success -- and a retry applies the change again.
    """

    MARKER = "MCP-PARTIAL-WRITE-MUST-NOT-SURVIVE"

    def _partner_count_by_sql(self, name):
        """Count the marker partner through SQL.

        Deliberately not ``search_count``: after a savepoint rollback the ORM
        cache must be discarded anyway, so reading the table directly is what
        actually tells us whether the row survived.
        """
        self.env.cr.execute(
            "SELECT count(*) FROM res_partner WHERE name = %s", (name,)
        )
        return self.env.cr.fetchone()[0]

    def _call_with_exploding_tool(self):
        """Run one MCP tool call whose tool writes, then raises."""
        # Bound here, not read off ``self`` inside the fake: the patched
        # ``execute`` is called with the ``llm.tool`` record as its first
        # argument, so ``self`` in there is the record, not this TestCase.
        marker = self.MARKER

        def exploding_tool(self, parameters):
            self.env["res.partner"].create({"name": marker})
            raise UserError("boom, after the write")

        with patch.object(type(self.env["llm.tool"]), "execute", exploding_tool):
            return self.env["llm.tool"].execute_mcp_tool(
                {
                    "name": "odoo_record_retriever",
                    "arguments": {"model": "res.partner", "limit": 1},
                }
            )

    def test_failed_tool_does_not_leave_writes_behind(self):
        result = self._call_with_exploding_tool()

        self.assertTrue(result.is_error)
        self.assertEqual(
            self._partner_count_by_sql(self.MARKER),
            0,
            "the failed tool's write survived the failed call: the tool call "
            "needs to run inside a savepoint",
        )

    def test_failed_tool_is_still_audited(self):
        """Rolling the work back must not swallow the audit row.

        The audit write happens after the tool call, so it has to stay outside
        the savepoint -- a failed call is exactly the one worth recording.
        """
        audit = self.env["llm.mcp.tool.call"]
        domain = [("tool_name", "=", "odoo_record_retriever")]
        before = audit.search_count(domain)

        self._call_with_exploding_tool()

        rows = audit.search(domain)
        self.assertEqual(len(rows), before + 1)
        self.assertTrue(rows[0].is_error)
        self.assertIn("boom, after the write", rows[0].result_summary)
