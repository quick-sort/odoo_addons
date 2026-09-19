import json
from unittest import mock

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.infohub_agent.models.infohub_item import TAGGER_CODE

from .common import StubSelectionMixin


@tagged("post_install", "-at_install")
class TestTaggingJob(StubSelectionMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._open_selections()
        cls.channel = cls._make_channel()
        cls.agent = cls.env["llm.agent"].search([("code", "=", TAGGER_CODE)])
        cls.tag_clinical = cls.env["infohub.tag"].create(
            {"name": "Clinical", "code": "clinical", "description": "Trials."}
        )
        cls.tag_ai = cls.env["infohub.tag"].create(
            {"name": "AI", "code": "ai", "description": "Model releases."}
        )
        cls._configure_agent()

    @classmethod
    def _configure_agent(cls):
        """Provider and model are per environment; the job needs them set."""
        provider = cls._make_provider()
        model = cls.env["llm.model"].create(
            {"name": "test-model", "provider_id": provider.id}
        )
        cls.agent.write({"provider_id": provider.id, "model_id": model.id})

    def _make_item(self, title):
        return self.env["infohub.item"].create(
            {"channel_id": self.channel.id, "title": title}
        )

    def _invoke_returning(self, payload=None, error=None):
        """Patch ``llm.agent.invoke`` with a canned answer.

        Patched on the class so it also covers the ``sudo()`` recordset the
        job calls through.
        """
        result = {"result": payload, "error": error, "thread_id": None}
        return mock.patch.object(
            type(self.env["llm.agent"]), "invoke", return_value=result
        )

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def test_cron_claims_items_and_enqueues_jobs(self):
        items = self.env["infohub.item"].create(
            [
                {"channel_id": self.channel.id, "title": f"Headline {i}"}
                for i in range(3)
            ]
        )
        self.env["infohub.item"]._cron_enqueue_tagging()

        self.assertEqual(set(items.mapped("tagging_state")), {"queued"})
        jobs = self.env["queue.job"].search(
            [("identity_key", "like", "infohub-tagging-%")]
        )
        self.assertEqual(len(jobs), 1)

    def test_cron_is_a_noop_without_taxonomy(self):
        self.env["infohub.tag"].search([]).unlink()
        item = self._make_item("Headline")
        self.env["infohub.item"]._cron_enqueue_tagging()
        self.assertEqual(item.tagging_state, "pending")

    def test_cron_is_a_noop_without_configured_agent(self):
        self.agent.write({"provider_id": False, "model_id": False})
        item = self._make_item("Headline")
        self.env["infohub.item"]._cron_enqueue_tagging()
        self.assertEqual(item.tagging_state, "pending")

    # ------------------------------------------------------------------
    # Job
    # ------------------------------------------------------------------

    def test_job_tags_items(self):
        items = self.env["infohub.item"].create(
            [
                {"channel_id": self.channel.id, "title": "Phase III trial results"},
                {"channel_id": self.channel.id, "title": "Local weather report"},
            ]
        )
        items.write({"tagging_state": "queued"})
        answer = json.dumps(
            {
                "results": [
                    {"id": items[0].id, "tags": ["clinical"]},
                    {"id": items[1].id, "tags": []},
                ]
            }
        )
        with self._invoke_returning(answer):
            items._job_tag_items()

        self.assertEqual(items[0].tag_ids, self.tag_clinical)
        self.assertEqual(items[0].tagging_state, "done")
        self.assertFalse(items[1].tag_ids)
        self.assertEqual(items[1].tagging_state, "skipped")

    def test_job_sends_titles_only(self):
        item = self._make_item("Phase III trial results")
        item.tagging_state = "queued"
        with self._invoke_returning(
            json.dumps({"results": [{"id": item.id, "tags": []}]})
        ) as patched:
            item._job_tag_items()

        # invoke is patched on the class, so it is a plain mock rather than a
        # bound method: the query is the first positional argument.
        query = patched.call_args[0][0]
        self.assertIn("Phase III trial results", query)
        self.assertIn("clinical", query)
        self.assertTrue(patched.call_args[1].get("new_cursor") is False)

    def test_job_parses_fenced_answer(self):
        item = self._make_item("A model release")
        item.tagging_state = "queued"
        answer = "```json\n%s\n```" % json.dumps(
            {"results": [{"id": item.id, "tags": ["ai"]}]}
        )
        with self._invoke_returning(answer):
            item._job_tag_items()
        self.assertEqual(item.tag_ids, self.tag_ai)

    def test_job_parses_html_wrapped_answer(self):
        item = self._make_item("A model release")
        item.tagging_state = "queued"
        answer = "<p>%s</p>" % json.dumps(
            {"results": [{"id": item.id, "tags": ["ai"]}]}
        )
        with self._invoke_returning(answer):
            item._job_tag_items()
        self.assertEqual(item.tag_ids, self.tag_ai)

    def test_job_drops_unknown_codes_and_ids(self):
        item = self._make_item("Phase III trial results")
        item.tagging_state = "queued"
        answer = json.dumps(
            {
                "results": [
                    {"id": item.id, "tags": ["clinical", "invented"]},
                    {"id": 999999, "tags": ["ai"]},
                ]
            }
        )
        with self._invoke_returning(answer):
            item._job_tag_items()

        self.assertEqual(item.tag_ids, self.tag_clinical)
        self.assertEqual(item.tagging_state, "done")

    def test_job_records_malformed_answer_without_raising(self):
        item = self._make_item("Headline")
        item.tagging_state = "queued"
        with self._invoke_returning("I cannot help with that."):
            item._job_tag_items()

        self.assertEqual(item.tagging_state, "error")
        self.assertTrue(item.tagging_error)

    def test_job_records_agent_error(self):
        item = self._make_item("Headline")
        item.tagging_state = "queued"
        with self._invoke_returning(error="boom"):
            item._job_tag_items()

        self.assertEqual(item.tagging_state, "error")
        self.assertEqual(item.tagging_error, "boom")

    def test_job_releases_claim_when_taxonomy_disappears(self):
        item = self._make_item("Headline")
        item.tagging_state = "queued"
        self.env["infohub.tag"].search([]).unlink()
        item._job_tag_items()
        self.assertEqual(item.tagging_state, "pending")

    def test_job_ignores_items_that_are_not_queued(self):
        item = self._make_item("Headline")
        item.tagging_state = "queued"
        other = self._make_item("Untouched")
        with self._invoke_returning(
            json.dumps({"results": [{"id": item.id, "tags": ["ai"]}]})
        ):
            item._job_tag_items()

        self.assertEqual(other.tagging_state, "pending")
        self.assertFalse(other.tag_ids)

    def test_retagging_replaces_existing_tags(self):
        item = self._make_item("Phase III trial results")
        item.write({"tag_ids": [(6, 0, self.tag_ai.ids)], "tagging_state": "queued"})
        answer = json.dumps({"results": [{"id": item.id, "tags": ["clinical"]}]})
        with self._invoke_returning(answer):
            item._job_tag_items()

        self.assertEqual(item.tag_ids, self.tag_clinical)

    def test_requeue_resets_state(self):
        item = self._make_item("Headline")
        item.write({"tagging_state": "error", "tagging_error": "boom"})
        item.action_requeue_tagging()
        self.assertEqual(item.tagging_state, "pending")
        self.assertFalse(item.tagging_error)
