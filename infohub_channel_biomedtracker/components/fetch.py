"""Pull event rows from BioMedTracker's advanced event search.

The endpoint is a DataTables-style paged search. One fetch walks the pages
until the server stops returning new rows. Rows sharing Company + Drug +
Event Type + Event Date are merged into one item upstream, so the InfoHub pool
stays free of near-duplicates.
"""

import datetime
import hashlib
import logging

import requests

from odoo.addons.component.core import Component
from odoo.addons.infohub_channel_biomedtracker.components.content import (
    MULTI_FIELDS,
)

_logger = logging.getLogger(__name__)

_BASE_URL = "https://www.biomedtracker.com"
_EVENT_PATH = (
    "/components/AdvancedEventSearch.cfc"
    "?method=getEventSearchResultsPaged&ResultType=Events"
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

TIMEOUT = 60
PAGE_SIZE = 200
MAX_PAGES = 50

_COLUMNS = [
    ("EVENTDATE", True),
    ("EVENTHEADLINE", True),
    ("EVENTTYPE", True),
    ("REGIONNAME", True),
    ("PHASENAME", True),
    ("CURRENTPHASE", True),
    ("TRIALS", False),
    ("SOURCENAME", False),
    ("BRANDNAME", True),
    ("OTHERNAMES", True),
    ("GENERICNAME", True),
    ("INDICATIONNAME", True),
    ("SUBSUBINDICATIONNAME", True),
    ("LEADINDICATIONFLAG", True),
    ("RAREDISEASE", True),
    ("CLASSES", False),
    ("ROUTES", False),
    ("MOLECULENAME", False),
    ("TARGETS", False),
    ("DESIGNATIONS", False),
    ("DRUGFEATURES", False),
    ("OVERALLCHANGE", True),
    ("CUMULATIVESCORE", True),
    ("OBJECTIVESCORE", True),
    ("COMPANYNAME", True),
    ("TYPENAME", True),
    ("MARKETCAP", True),
    ("CITY", True),
    ("STATEPROVNAME", True),
    ("COUNTRYNAME", True),
    ("CONTINENTNAME", True),
    ("PARTNERCOMPANYLIST", False),
    ("OWNERSHIPPCT", True),
    ("FORMERCOMPANYLIST", False),
]
# Column indices the server is asked to return; SOURCELINK rides along without
# being declared in the column list (the server appends it to row dicts).
_DEFAULT_EVENT_COLUMNS = "0,1,2,3,6,9,10,11,14,15,16,18,20,21,27"

# Fields that should never be merged — IDs, counters, numeric scores.
_NO_MERGE_FIELDS = frozenset({
    "DRUGEVENTID", "DRUGINDICATIONID", "SUBSUBINDICATIONID", "INDICATIONID",
    "DRUGID", "COMPANYID", "PHASEID", "EVENTTYPEID",
    "RECORDSTOTAL", "RECORDSFILTERED",
    "MARKETCAP", "OVERALLCHANGE", "CUMULATIVESCORE", "OBJECTIVESCORE",
    "OWNERSHIPPCT", "YEARFOUNDED", "SYMBOL",
    "CREATIONDATE", "SOURCEDATE",
})


def _union_multi(existing, incoming):
    """Union two pipe-separated multi-value fields, preserving order.

    ``TARGETS=123^IL-23|456^IL-12`` and ``TARGETS=123^IL-23`` describe the
    same target set; joining them with the generic separator would corrupt the
    ``id^name`` encoding, so the pieces are unioned on ``|`` instead.
    """
    pieces = [p.strip() for p in (existing or "").split("|") if p.strip()]
    for piece in (incoming or "").split("|"):
        piece = piece.strip()
        if piece and piece not in pieces:
            pieces.append(piece)
    return "|".join(pieces)


def _fmt_date(d):
    if hasattr(d, "strftime"):
        return d.strftime("%m/%d/%Y")
    return d


def _build_params(date_from, date_to, start, length, order_col, order_dir, filters):
    params = {
        "draw": "1",
        "order[0][column]": str(order_col),
        "order[0][dir]": order_dir,
        "start": str(start),
        "length": str(length),
        "search[value]": "",
        "search[regex]": "false",
        "PhaseID": "",
        "EventRegionID": "",
        "TrialSubPhaseID": "",
        "Event_SourceTypeID": "",
        "CompanyID": "",
        "PortfolioID": "",
        "DrugID": "",
        "GenericName": "",
        "ProductPortfolioID": "",
        "IndicationID": "",
        "SubSubIndicationID": "",
        "DrugSubPhaseID": "",
        "MoleculeID": "",
        "TargetID": "",
        "ClassID": "",
        "RouteID": "",
        "DesignationID": "",
        "TherapyLineID": "",
        "DrugFeatureID": "",
        "EventColumns": _DEFAULT_EVENT_COLUMNS,
        "DrugEventIDs": "",
        "EmailReferenceID": "",
        "Keyword": "",
        "AdditionalKeywordCounter": "0",
        "DBDate1": _fmt_date(date_from),
        "DBDate2": _fmt_date(date_to),
        "EventTypeID": "",
        "HasSagientComment": "0",
        "Ticker": "",
        "CompanyTypeID": "",
        "LeadCompany": "",
        "MarketCapLow": "",
        "MarketCapLowUOM": "M",
        "MarketCapHigh": "",
        "MarketCapHighUOM": "M",
        "GeographyTreeIDs": "",
        "CompanyFoundedYearMin": "",
        "CompanyFoundedYearMax": "",
        "Partner": "",
        "LeadIndication": "",
        "LOA1": "",
        "LOA2": "",
        "BMTAPP1": "",
        "BMTAPP2": "",
        "RareDisease": "",
    }
    for i, (name, orderable) in enumerate(_COLUMNS):
        p = f"columns[{i}]"
        params[f"{p}[data]"] = name
        params[f"{p}[name]"] = ""
        params[f"{p}[searchable]"] = "true"
        params[f"{p}[orderable]"] = "true" if orderable else "false"
        params[f"{p}[search][value]"] = ""
        params[f"{p}[search][regex]"] = "false"
    params.update(filters)
    return params


class InfohubFetchBiomedtracker(Component):
    _name = "infohub.fetch.biomedtracker"
    _inherit = "infohub.fetch"
    _usage = "infohub.fetch.biomedtracker"

    def fetch_news(self, date_from=None, date_to=None, **kwargs):
        """Return ``(request_params, items)``.

        Without explicit dates, yesterday-to-today is fetched — the window the
        periodic cron wants. When the stored session cookie has gone stale, one
        login is re-run and the fetch retried: a 200 carrying the HTML login
        page instead of JSON is the symptom, so a decode error triggers the
        retry.
        """
        channel = self.collection
        if not channel._biomedtracker_cookie():
            raise ValueError(
                "No BioMedTracker cookie: run Login or set a manual cookie."
            )
        if date_from is None:
            date_from = datetime.date.today() - datetime.timedelta(days=1)
        if date_to is None:
            date_to = datetime.date.today()

        try:
            return self._search(date_from, date_to), self._paged_items(date_from, date_to)
        except ValueError:
            _logger.info(
                "infohub biomedtracker: session expired on %s, re-logging in",
                channel.display_name,
            )
            self._relogin()
            return self._search(date_from, date_to), self._paged_items(date_from, date_to)

    # ------------------------------------------------------------------

    def _search(self, date_from, date_to):
        params = _build_params(
            date_from, date_to, start=0, length=PAGE_SIZE,
            order_col=0, order_dir="desc", filters={},
        )
        # Return the first page's params as the recorded request payload —
        # representative of every page request, minus the moving cursor.
        return {k: v for k, v in params.items() if not k.startswith("columns[")}

    def _paged_items(self, date_from, date_to):
        items = []
        start = 0
        for _page in range(MAX_PAGES):
            data, total = self._request_page(date_from, date_to, start)
            if not data:
                break
            items.extend(data)
            start += len(data)
            if total and start >= total:
                break
        return self._merge_items(items)

    def _request_page(self, date_from, date_to, start):
        http = requests.Session()
        http.headers.update(
            {
                "User-Agent": _USER_AGENT,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{_BASE_URL}/aessearch.cfm",
                "Cookie": self.collection._biomedtracker_cookie(),
            }
        )
        data = _build_params(
            date_from, date_to, start=start, length=PAGE_SIZE,
            order_col=0, order_dir="desc", filters={},
        )
        resp = http.post(f"{_BASE_URL}{_EVENT_PATH}", data=data, timeout=TIMEOUT)
        resp.raise_for_status()
        result = resp.json()

        rows = result.get("data") or []
        # DataTables may return rows as lists — normalize to dicts.
        normalized = [
            {col[0]: row[i] for i, col in enumerate(_COLUMNS) if i < len(row)}
            if isinstance(row, list) else row
            for row in rows
        ]
        return normalized, result.get("recordsTotal") or 0

    def _relogin(self):
        channel = self.collection
        if not (channel.biomedtracker_username and channel.biomedtracker_password):
            raise ValueError(
                "BioMedTracker session expired and no credentials are set "
                "to re-login."
            )
        self.component(usage="infohub.login.biomedtracker").login()

    @classmethod
    def _merge_items(cls, items):
        """Merge rows sharing the same Company + Drug + Event Type + Date.

        Text fields that differ across merged rows are joined with ``' / '``.
        ID/numeric fields keep the first row's value. The merge key doubles as
        a stable ``external_id`` — server row IDs shift between fetches, but
        InfoHub deduplicates on it, so every merged row carries the hash of
        its key.
        """
        groups = {}
        order = []
        for item in items:
            key = (
                (item.get("COMPANYNAME") or "").strip(),
                (item.get("BRANDNAME") or "").strip(),
                (item.get("EVENTTYPE") or "").strip(),
                (item.get("EVENTDATE") or "").strip(),
            )
            if key not in groups:
                groups[key] = dict(item)
                order.append(key)
            else:
                merged = groups[key]
                for field, val in item.items():
                    if field in _NO_MERGE_FIELDS:
                        continue
                    if not isinstance(val, str):
                        continue
                    val = val.strip()
                    existing = merged.get(field)
                    if not isinstance(existing, str):
                        continue
                    existing = existing.strip()
                    if field in MULTI_FIELDS:
                        merged[field] = _union_multi(existing, val)
                    elif val and val not in existing.split(" / "):
                        merged[field] = f"{existing} / {val}" if existing else val
        results = []
        for key in order:
            row = groups[key]
            row["external_id"] = "bmt:" + hashlib.sha1(
                "\x1f".join(key).encode()
            ).hexdigest()[:24]
            results.append(row)
        return results
