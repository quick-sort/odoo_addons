"""Interpret BioMedTracker's event-row payload shape."""

import datetime

from odoo.addons.component.core import Component

#: Pipe-separated multi-value fields; some entries are "<id>^<name>" encoded.
#: Shared with the fetch component, which unions these on ``|`` when merging
#: rows — joining them with the generic separator would corrupt the encoding.
MULTI_FIELDS = ("TARGETS", "ROUTES", "DRUGFEATURES", "DESIGNATIONS", "CLASSES")


class InfohubContentBiomedtracker(Component):
    _name = "infohub.content.biomedtracker"
    _inherit = "infohub.content"
    _usage = "infohub.content.biomedtracker"

    def build_content(self, raw_data):
        data = dict(raw_data or {})
        for key in MULTI_FIELDS:
            if data.get(key):
                data[key] = self._clean_multi(data[key])
        lines = self._labelled(data, [
            ("Headline", "EVENTHEADLINE"),
            ("Event Type", "EVENTTYPE"),
            ("Company", "COMPANYNAME"),
            ("Drug", "BRANDNAME"),
            ("Generic", "GENERICNAME"),
            ("Target", "TARGETS"),
            ("Modality", "MOLECULENAME"),
            ("Class", "CLASSES"),
            ("Route", "ROUTES"),
            ("Drug Features", "DRUGFEATURES"),
            ("Designations", "DESIGNATIONS"),
            ("Indication", "INDICATIONNAME"),
            ("Sub-indication", "SUBSUBINDICATIONNAME"),
            ("Phase", "PHASENAME"),
            ("Current Phase", "CURRENTPHASE"),
            ("Region", "REGIONNAME"),
            ("Source", "SOURCENAME"),
        ])
        return "\n".join(lines)

    def subject(self, raw_data):
        data = raw_data or {}
        drug = data.get("BRANDNAME") or data.get("GENERICNAME") or ""
        parts = [
            data.get("EVENTTYPE") or "",
            data.get("INDICATIONNAME") or "",
            self._clean_multi(data["TARGETS"]) if data.get("TARGETS") else "",
            drug,
            self._clean_multi(data["CLASSES"]) if data.get("CLASSES") else "",
            data.get("TYPENAME") or "",
        ]
        return " | ".join(p for p in parts if p and p.strip().lower() != "unknown")

    def url(self, raw_data):
        # Rows carry the originating press-release link, when the search was
        # asked for that column.
        return (raw_data or {}).get("SOURCELINK") or ""

    def source(self, raw_data):
        return (raw_data or {}).get("SOURCENAME") or ""

    def date(self, raw_data):
        raw = (raw_data or {}).get("EVENTDATE") or ""
        if not raw:
            return ""
        try:
            return datetime.datetime.strptime(
                raw.strip(), "%B, %d %Y %H:%M:%S"
            ).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return ""

    @staticmethod
    def _clean_multi(value):
        """Render a pipe-separated, optionally ``id^name`` encoded field as a
        comma-joined list of plain names."""
        names = []
        for piece in str(value).split("|"):
            name = piece.split("^")[-1].strip()
            if name:
                names.append(name)
        return ", ".join(names)
