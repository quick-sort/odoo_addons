"""Tests for the BioMedTracker channel — all network stubbed offline."""

import datetime
from unittest import mock

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.infohub_channel_biomedtracker.components.fetch import (
    InfohubFetchBiomedtracker,
    _build_params,
)

ROW_A = {
    "EVENTDATE": "August, 14 2026 10:00:00",
    "EVENTHEADLINE": "Positive topline Phase 3 data",
    "EVENTTYPE": "Data Readout",
    "REGIONNAME": "United States",
    "PHASENAME": "Phase 3",
    "CURRENTPHASE": "Phase 3",
    "SOURCENAME": "Business Wire",
    "SOURCELINK": "https://www.businesswire.com/pr/1",
    "BRANDNAME": "Zynk",
    "GENERICNAME": "zynkibart",
    "INDICATIONNAME": "Ulcerative Colitis",
    "SUBSUBINDICATIONNAME": "",
    "TARGETS": "123^IL-23|456^IL-12",
    "CLASSES": "9^Monoclonal antibody",
    "MOLECULENAME": "mAb",
    "COMPANYNAME": "Acme Pharma",
    "TYPENAME": "Commercial-stage",
    "DESIGNATIONS": "",
    "ROUTES": "1^Subcutaneous",
    "DRUGFEATURES": "",
    "DRUGEVENTID": "1",
}
# Same Company + Drug + Event Type + Date as ROW_A — must merge into one item.
ROW_B = {
    "EVENTDATE": "August, 14 2026 10:00:00",
    "EVENTHEADLINE": "Positive topline Phase 3 data",
    "EVENTTYPE": "Data Readout",
    "BRANDNAME": "Zynk",
    "COMPANYNAME": "Acme Pharma",
    "SOURCENAME": "PR Newswire",
    "INDICATIONNAME": "Crohn's Disease",
    "TARGETS": "123^IL-23",
    "DRUGEVENTID": "999",
}
# Different drug — stays separate.
ROW_C = {
    "EVENTDATE": "August, 15 2026 09:00:00",
    "EVENTTYPE": "FDA Approval",
    "BRANDNAME": "Velora",
    "GENERICNAME": "veloratide",
    "COMPANYNAME": "Beta Bio",
    "SOURCENAME": "GlobeNewswire",
    "INDICATIONNAME": "CKD",
    "COMPANYID": "77",
}


def _page_response(rows, records_total):
    response = mock.MagicMock()
    response.is_redirect = False
    response.headers = {}
    response.json.return_value = {
        "data": rows,
        "recordsTotal": records_total,
        "recordsFiltered": records_total,
    }
    return response


@tagged("post_install", "-at_install")
class TestBiomedtrackerChannel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["infohub.channel"]

    def _channel(self, **vals):
        return self.Channel.create(
            {
                "name": "BioMedTracker",
                "channel_type": "biomedtracker",
                "biomedtracker_manual_cookie": "sessionid=stub",
                **vals,
            }
        )

    # ------------------------------------------------------------------
    # Channel type
    # ------------------------------------------------------------------

    def test_biomedtracker_is_a_selectable_channel_type(self):
        selection = dict(self.Channel._fields["channel_type"].selection)
        self.assertIn("biomedtracker", selection)

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def test_params_carry_dates_in_server_format(self):
        params = _build_params(
            datetime.date(2026, 9, 1), datetime.date(2026, 9, 16),
            start=0, length=200, order_col=0, order_dir="desc", filters={},
        )
        self.assertEqual(params["DBDate1"], "09/01/2026")
        self.assertEqual(params["DBDate2"], "09/16/2026")
        self.assertEqual(params["start"], "0")
        self.assertEqual(params["length"], "200")

    # ------------------------------------------------------------------
    # Row merging
    # ------------------------------------------------------------------

    def test_rows_sharing_identity_merge(self):
        merged = InfohubFetchBiomedtracker._merge_items([ROW_A, ROW_B])
        self.assertEqual(len(merged), 1)
        row = merged[0]
        # Differing text fields join with ' / '.
        self.assertEqual(row["SOURCENAME"], "Business Wire / PR Newswire")
        self.assertEqual(row["INDICATIONNAME"], "Ulcerative Colitis / Crohn's Disease")
        # ID/numeric fields keep the first row's value.
        self.assertEqual(row["DRUGEVENTID"], "1")
        # Multi-value fields union on '|' rather than the generic separator,
        # so the id^name encoding survives and the shared target is not
        # duplicated.
        self.assertEqual(row["TARGETS"], "123^IL-23|456^IL-12")

    def test_merged_multi_field_renders_as_clean_names(self):
        """A unioned multi-value field still renders without '^' or ' / '."""
        merged = InfohubFetchBiomedtracker._merge_items([ROW_A, ROW_B])[0]
        channel = self._channel()
        text = channel.build_content(merged)
        self.assertIn("Target: IL-23, IL-12", text)
        self.assertNotIn("^", text)

    def test_distinct_drugs_do_not_merge(self):
        merged = InfohubFetchBiomedtracker._merge_items([ROW_A, ROW_C])
        self.assertEqual(len(merged), 2)

    # ------------------------------------------------------------------
    # Content shaping
    # ------------------------------------------------------------------

    def test_subject_joins_meaningful_parts(self):
        channel = self._channel()
        subject = channel.subject(ROW_A)
        self.assertIn("Zynk", subject)
        self.assertIn("Ulcerative Colitis", subject)
        self.assertIn("Data Readout", subject)

    def test_date_parses_event_date(self):
        channel = self._channel()
        self.assertEqual(
            channel.date(ROW_A), "2026-08-14 10:00:00"
        )
        self.assertEqual(channel.date({"EVENTDATE": "garbage"}), "")

    def test_url_is_press_release_link(self):
        channel = self._channel()
        self.assertEqual(channel.url(ROW_A), "https://www.businesswire.com/pr/1")
        self.assertEqual(channel.url({}), "")

    def test_content_renders_multi_fields_as_plain_names(self):
        channel = self._channel()
        text = channel.build_content(ROW_A)
        self.assertIn("Target: IL-23, IL-12", text)
        self.assertIn("Class: Monoclonal antibody", text)
        self.assertIn("Route: Subcutaneous", text)

    def test_source_is_sourcename(self):
        channel = self._channel()
        self.assertEqual(channel.source(ROW_A), "Business Wire")

    # ------------------------------------------------------------------
    # Fetch + ingest
    # ------------------------------------------------------------------

    def _stub_pages(self, pages):
        """Patch the transport seam; ``pages`` is a list of responses, one per
        POST the fetch makes."""
        return mock.patch(
            "odoo.addons.infohub_channel_biomedtracker.components.fetch.requests.Session.post",
            side_effect=pages,
        )

    def test_fetch_without_cookie_raises(self):
        channel = self.Channel.create(
            {"name": "BMT", "channel_type": "biomedtracker"}
        )
        with self.assertRaises(ValueError):
            channel.fetch_news()

    def test_fetch_and_ingest_end_to_end(self):
        channel = self._channel()
        with self._stub_pages([_page_response([ROW_A, ROW_B, ROW_C], 3)]):
            channel.action_fetch()

        items = self.env["infohub.item"].search([("channel_id", "=", channel.id)])
        # ROW_A + ROW_B merged; ROW_C separate.
        self.assertEqual(len(items), 2)
        titles = items.mapped("title")
        self.assertTrue(any("Zynk" in t for t in titles))
        self.assertTrue(any("Velora" in t for t in titles))

    def test_refetch_does_not_duplicate(self):
        channel = self._channel()
        with self._stub_pages([_page_response([ROW_A, ROW_C], 2)]):
            channel.action_fetch()
        with self._stub_pages([_page_response([ROW_A, ROW_C], 2)]):
            channel.action_fetch()

        items = self.env["infohub.item"].search([("channel_id", "=", channel.id)])
        self.assertEqual(len(items), 2)

    def test_pagination_walks_all_pages(self):
        channel = self._channel()
        page1 = _page_response([ROW_A], 2)
        page2 = _page_response([ROW_C], 2)
        with self._stub_pages([page1, page2]):
            channel.action_fetch()

        items = self.env["infohub.item"].search([("channel_id", "=", channel.id)])
        self.assertEqual(len(items), 2)

    def test_stale_session_triggers_relogin_and_retry(self):
        channel = self._channel(
            biomedtracker_username="user@example.com",
            biomedtracker_password="secret",
        )
        # A stale cookie gets the HTML login page: json() fails to decode.
        login_page = mock.MagicMock()
        login_page.json.side_effect = ValueError("Expecting value")
        fresh_page = _page_response([ROW_A], 1)

        from odoo.addons.infohub_channel_biomedtracker.components.login import (
            InfohubLoginBiomedtracker,
        )

        def fake_login(comp_self):
            comp_self.collection.biomedtracker_session_cookie = "appSession=fresh"

        with mock.patch.object(
            InfohubLoginBiomedtracker, "login", fake_login
        ), self._stub_pages([login_page, fresh_page]):
            channel.action_fetch()

        items = self.env["infohub.item"].search([("channel_id", "=", channel.id)])
        self.assertEqual(len(items), 1)
        self.assertEqual(channel.biomedtracker_session_cookie, "appSession=fresh")

    def test_external_id_survives_shifting_row_ids(self):
        """Merged row identity comes from the merge key, not the server row ID."""
        first = InfohubFetchBiomedtracker._merge_items([ROW_A])[0]
        second = InfohubFetchBiomedtracker._merge_items(
            [dict(ROW_A, DRUGEVENTID="424242")]
        )[0]
        self.assertTrue(first["external_id"])
        self.assertEqual(first["external_id"], second["external_id"])
