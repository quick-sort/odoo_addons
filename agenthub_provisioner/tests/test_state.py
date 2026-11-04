from odoo.tests import common, tagged

from odoo.addons.agenthub_provisioner.contract import ContainerState

from .common import ProvisionerCaseMixin


@tagged("post_install", "-at_install")
class TestProvisionerState(ProvisionerCaseMixin, common.TransactionCase):
    def _jobs(self):
        jobs = self.env["queue.job"].search(
            [("model_name", "=", "agenthub.agent.deployment")]
        )
        return jobs.filtered(
            lambda job: self.deployment.id in (job.records.ids or [])
        )

    def test_action_apply_enqueues_job(self):
        self.deployment.action_apply()

        self.assertEqual(self.deployment.desired_state, "running")
        self.assertEqual(self.deployment.state, "provisioning")
        job = self._jobs()
        self.assertEqual(len(job), 1)
        self.assertEqual(job.method_name, "_job_apply")
        self.assertEqual(job.channel, "root.agenthub")
        self.assertEqual(
            job.identity_key,
            "agenthub_provisioner.deployment.%s" % self.deployment.id,
        )

    def test_job_apply_success(self):
        spec = self.deployment._render_spec()
        self.driver.apply_result = ContainerState(
            id="cid-42",
            name=spec.name,
            status="running",
            labels=dict(spec.labels),
        )

        self.deployment._job_apply()

        self.assertEqual(self.deployment.state, "running")
        self.assertEqual(self.deployment.runtime_id, "cid-42")
        self.assertEqual(self.deployment.config_hash, spec.config_hash)
        self.assertFalse(self.deployment.config_drift)
        self.assertFalse(self.deployment.last_error)
        self.assertEqual(
            self.agent.token_hash,
            self.agent._hash_token(self.agent._provisioner_token()),
        )

    def test_job_apply_failure_records_error(self):
        self.driver.fail = "apply"

        self.deployment._job_apply()

        self.assertEqual(self.deployment.state, "error")
        self.assertIn("CREATE_FAILED", self.deployment.last_error)
        self.assertNotIn(self.agent._provisioner_token(), self.deployment.last_error)

    def test_job_stop(self):
        self.deployment.write({"runtime_id": "cid-42"})

        self.deployment._job_stop()

        self.assertEqual(self.deployment.state, "stopped")
        self.assertEqual(self.driver.calls[0], ("stop", "cid-42", 10))

    def test_job_stop_failure(self):
        self.driver.fail = "stop"
        self.deployment._job_stop()

        self.assertEqual(self.deployment.state, "error")
        self.assertIn("STOP_FAILED", self.deployment.last_error)

    def test_job_remove(self):
        self.deployment.write({"runtime_id": "cid-42", "config_hash": "abc"})

        self.deployment._job_remove()

        self.assertEqual(self.deployment.state, "removed")
        self.assertFalse(self.deployment.runtime_id)
        self.assertFalse(self.deployment.config_hash)
        self.assertEqual(self.driver.calls[0], ("remove", "cid-42"))

    def test_sync_detects_drift(self):
        self.deployment.write({"state": "running", "runtime_id": "cid-42"})
        self.driver.status_result = ContainerState(
            id="cid-42",
            name=self.deployment.container_name,
            status="running",
            labels={"agenthub.config_hash": "stale"},
        )

        self.deployment._sync_status()

        self.assertTrue(self.deployment.config_drift)
        self.assertEqual(self.deployment.state, "running")

    def test_sync_clears_drift_when_hash_matches(self):
        spec = self.deployment._render_spec()
        self.deployment.write({"state": "running", "runtime_id": "cid-42"})
        self.driver.status_result = ContainerState(
            id="cid-42",
            name=self.deployment.container_name,
            status="running",
            labels=dict(spec.labels),
        )

        self.deployment._sync_status()

        self.assertFalse(self.deployment.config_drift)

    def test_sync_missing_with_desired_running_is_error(self):
        self.deployment.write({"state": "running", "desired_state": "running"})
        self.driver.status_result = ContainerState(
            id=None,
            name=self.deployment.container_name,
            status="missing",
        )

        self.deployment._sync_status()

        self.assertEqual(self.deployment.state, "error")
        self.assertIn("missing", self.deployment.last_error.lower())

    def test_sync_missing_with_desired_stopped_is_stopped(self):
        self.deployment.write({"state": "stopped", "desired_state": "stopped"})
        self.driver.status_result = ContainerState(
            id=None,
            name=self.deployment.container_name,
            status="missing",
        )

        self.deployment._sync_status()

        self.assertEqual(self.deployment.state, "stopped")

    def test_cron_skips_offline_host(self):
        self.deployment.write({"state": "running", "desired_state": "running"})
        self.driver.fail = "probe"

        self.env["agenthub.agent.deployment"]._cron_reconcile()

        self.assertEqual(self.deployment.state, "running")
        self.assertFalse(
            any(call[0] == "status" for call in self.driver.calls)
        )

    def test_cron_skips_in_progress(self):
        self.deployment.write({"state": "provisioning", "desired_state": "running"})

        self.env["agenthub.agent.deployment"]._cron_reconcile()

        self.assertFalse(
            any(call[0] == "status" for call in self.driver.calls)
        )

    def test_cron_auto_heal_enqueues_apply(self):
        self.deployment.write(
            {
                "state": "running",
                "desired_state": "running",
                "auto_heal": True,
            }
        )
        self.driver.status_result = ContainerState(
            id=None,
            name=self.deployment.container_name,
            status="missing",
        )

        self.env["agenthub.agent.deployment"]._cron_reconcile()

        self.assertEqual(self.deployment.state, "provisioning")
        self.assertEqual(len(self._jobs()), 1)
