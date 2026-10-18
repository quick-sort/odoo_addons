"""Pure-Python RST -> plain-text renderer + adaptive chunking.

Turns the Odoo user documentation (``content/applications`` of the
``odoo/documentation`` repo) into a list of ``llm.tool.guide`` dicts. Used by
both the ``llm.odoo.guide.sync`` model (runtime web update) and the
``scripts/gen_odoo_guides.py`` CLI (offline XML generation).
"""
import os
import re

# ---------------------------------------------------------------- modules

MODULES = [
    ("essentials", "Essentials"),
    ("general", "General"),
    ("sales", "Sales"),
    ("finance", "Finance"),
    ("inventory_and_mrp", "Inventory & Manufacturing"),
    ("hr", "HR"),
    ("marketing", "Marketing"),
    ("productivity", "Productivity"),
    ("services", "Services"),
    ("websites", "Websites"),
    ("studio", "Studio"),
]

# human title for a sub-app slug
TITLE_OVERRIDES = {
    "accounting": "Accounting",
    "crm": "CRM",
    "point_of_sale": "Point of Sale",
    "pos": "POS",
    "iot": "IoT",
    "esg": "ESG",
    "plm": "PLM",
    "ai": "AI",
    "mrp": "Manufacturing",
    "hr": "HR",
    "to_do": "To-do",
    "sms_marketing": "SMS Marketing",
    "email_marketing": "Email Marketing",
    "marketing_automation": "Marketing Automation",
    "social_marketing": "Social Marketing",
    "field_service": "Field Service",
    "time_off": "Time Off",
    "in_app_purchase": "In-App Purchase",
    "html_editor": "HTML Editor",
    "export_import_data": "Export & Import Data",
    "keyboard_shortcuts": "Keyboard Shortcuts",
    "product_catalog": "Product Catalog",
    "fiscal_localizations": "Fiscal Localizations",
    "payment_providers": "Payment Providers",
    "developer_mode": "Developer Mode",
    "email_communication": "Email Communication",
    "apps_modules": "Apps & Modules",
}


def slug_title(slug):
    if slug in TITLE_OVERRIDES:
        return TITLE_OVERRIDES[slug]
    return slug.replace("_", " ").title()


# ---------------------------------------------------------------- RST renderer

UNDERLINE_CHARS = "=-~^\"'`#*+"


def _is_underline(s):
    s = s.strip()
    return bool(s) and len(s) >= 2 and len(set(s)) == 1 and s[0] in UNDERLINE_CHARS


HEADING_LEVEL = {
    "=": 1, "-": 2, "~": 3, "^": 4, '"': 4, "'": 4, "`": 4, "#": 3, "*": 3, "+": 3,
}

ADMONITIONS = {
    "note": "Note", "tip": "Tip", "warning": "Warning", "important": "Important",
    "danger": "Danger", "caution": "Caution", "seealso": "See also",
    "attention": "Attention", "hint": "Hint", "example": "Example",
    "todo": "TODO", "error": "Error", "warning_box": "Warning",
}

SKIP_DIRECTIVES = {
    "image", "figure", "toctree", "contents", "include", "literalinclude",
    "raw", "meta", "class", "role", "default-role", "highlight", "only",
    "versionadded", "versionchanged", "deprecated", "index", "sectionauthor",
    "codeauthor", "header", "footer", "topic", "rubric", "epigraph", "sidebar",
}


def _clean_inline(text):
    """Strip RST inline roles/markup, keep plain text."""
    # roles: :role:`content` -> content  (handle ref/doc with <anchor>)
    def role_repl(m):
        role = m.group(1)
        content = m.group(2)
        if role in ("menuselection", "kbd", "command", "guilabel", "abbr"):
            return content
        if role in ("ref", "doc", "numref"):
            # "label <anchor>" or "<anchor>"
            if content.startswith("<"):
                return ""
            content = re.sub(r"\s*<[^>]*>\s*$", "", content)
            return content
        # download/file/option/envvar/setting/icon/dfn/term/title/etc
        return content
    text = re.sub(r":([a-zA-Z][\w-]*):`([^`]*)`", role_repl, text)
    # external hyperlinks `text <url>`_  and `text`_
    text = re.sub(r"`([^`<]+)\s*<[^>]+>`_", r"\1", text)
    text = re.sub(r"`([^`]+)`_", r"\1", text)
    # substitution references |name| -> drop
    text = re.sub(r"\|[^|]+\|", "", text)
    # inline literals ``code``
    text = re.sub(r"``([^`]*)``", r"\1", text)
    # lone backticks `text`
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # bold **x**
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    # italic *x* (not a leading bullet)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    # backslash escapes
    text = text.replace("\\*", "*").replace("\\`", "`").replace("\\_", "_")
    return text.strip()


def _dedent(lines):
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    if not indents:
        return lines
    base = min(indents)
    return [l[base:] if l.strip() else "" for l in lines]


def _render_grid_table(lines, i):
    """Collect a grid table starting at lines[i] (a +---+ border)."""
    n = len(lines)
    rows = []
    j = i
    while j < n:
        s = lines[j].strip()
        if s.startswith("+"):
            j += 1
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            rows.append(cells)
            j += 1
            continue
        break
    text_rows = [" | ".join(r) for r in rows]
    return text_rows, j


def _render_list_table(content, out):
    """Render a .. list-table:: / .. csv-table:: directive body as pipe text."""
    rows = []
    cur = None
    for raw in content:
        s = raw.strip()
        if not s:
            if cur is not None:
                rows.append(cur)
                cur = None
            continue
        if re.match(r"^:\w[\w-]*:\s*", s):  # options like :header-rows: / :widths:
            continue
        m = re.match(r"^[-*]\s+-\s*(.*)$", s)  # first cell of a row
        if m:
            if cur is not None:
                rows.append(cur)
            cur = [_clean_inline(m.group(1))]
            continue
        m = re.match(r"^-\s*(.*)$", s)  # additional cell
        if m and cur is not None:
            cur.append(_clean_inline(m.group(1)))
            continue
        # csv-table data line (or unrecognized): emit as-is, comma cells
        if "," in s:
            rows.append([_clean_inline(c) for c in s.split(",")])
        else:
            out.append(_clean_inline(s))
    if cur is not None:
        rows.append(cur)
    for r in rows:
        out.append(" | ".join(r))


def _preclean(text):
    """Global removals that work regardless of nesting depth."""
    # image/figure/thumbnail directives (drop the directive line)
    text = re.sub(r"^(\s*)\.\.\s+(?:image|figure|thumbnail)::.*$", "", text, flags=re.M)
    # image bullets: "- .. image:: x.png"
    text = re.sub(r"^(\s*)[-*]\s+\.\.\s+(?:image|figure|thumbnail)::.*$", "", text, flags=re.M)
    # Sphinx rst-class directives (CSS class hooks, no content)
    text = re.sub(r"^(\s*)\.\.\s+rst-class::.*$", "", text, flags=re.M)
    # their option lines
    text = re.sub(
        r"^(\s*):(?:alt|scale|width|height|align|class|target|name|caption|"
        r"header-rows|stub-columns|widths|custom-css|custom-js|emphasize-lines|"
        r"tag|image|linenos|language|delim|quotechar|keepspace|option|value):.*$",
        "", text, flags=re.M,
    )
    # substitution definitions: .. |name| replace:: / .. |name| image:: (single line)
    text = re.sub(r"^(\s*)\.\.\s+\|[^|]+\|\s+\w+::.*$", "", text, flags=re.M)
    # substitution definitions: .. |name|  (name on its own line, body indented)
    text = re.sub(r"^(\s*)\.\.\s+\|[^|]+\|\s*$", "", text, flags=re.M)
    # bare field-list metadata (:nosearch:, :show-content:, ...)
    text = re.sub(r"^(\s*):[a-zA-Z][\w-]*:\s*$", "", text, flags=re.M)
    return text


def render_rst(text):
    text = _preclean(text)
    lines = text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        # blank
        if not stripped:
            out.append("")
            i += 1
            continue
        # document title with overline + underline  (====\nTitle\n====)
        if (_is_underline(stripped) and i + 2 < n
                and lines[i + 1].strip() and not _is_underline(lines[i + 1])
                and _is_underline(lines[i + 2])):
            ch = lines[i + 2].strip()[0]
            lvl = HEADING_LEVEL.get(ch, 3)
            out.append("#" * lvl + " " + _clean_inline(lines[i + 1].strip()))
            i += 3
            continue
        # heading (text line + matching underline)
        if i + 1 < n and _is_underline(lines[i + 1]) and len(lines[i + 1].strip()) >= len(stripped):
            ch = lines[i + 1].strip()[0]
            lvl = HEADING_LEVEL.get(ch, 3)
            out.append("#" * lvl + " " + _clean_inline(stripped))
            i += 2
            continue
        # grid table
        if stripped.startswith("+") and set(stripped) <= set("+-= "):
            rows, j = _render_grid_table(lines, i)
            out.extend(rows)
            i = j
            continue
        # directive (any indentation, so nested-in-list directives are caught)
        m = re.match(r"^(\s*)\.\.\s+([a-zA-Z_][\w-]*)::\s*(.*)$", line)
        if m:
            dname, darg = m.group(2), m.group(3).strip()
            dindent = len(line) - len(line.lstrip())
            j = i + 1
            content = []
            while j < n:
                l2 = lines[j]
                if l2.strip() == "":
                    content.append("")
                    j += 1
                    continue
                if len(l2) - len(l2.lstrip()) > dindent:
                    content.append(l2)
                    j += 1
                else:
                    break
            content = _dedent(content)
            _emit_directive(dname, darg, content, out)
            i = j
            continue
        # plain comment '..' or anchor '.. _name:'
        if re.match(r"^(\s*)\.\.\s*$", line) or re.match(r"^(\s*)\.\.\s+_\S+:", line):
            i += 1
            continue
        # field-list metadata like ':nosearch:' / ':show-content:'
        if re.match(r"^(\s*):[a-zA-Z][\w-]*:\s*$", line):
            i += 1
            continue
        # stray underline / table separator line
        if _is_underline(stripped):
            i += 1
            continue
        # normal text / list item
        out.append(_clean_inline(stripped))
        i += 1
    # collapse 3+ blank lines
    text = "\n".join(out)
    # drop any stray backticks left by line-wrapped inline markup
    text = text.replace("`", "")
    # leftover multi-line roles / links the per-line pass missed
    text = re.sub(r":([a-zA-Z][\w-]*):(?=\S)", "", text)
    text = re.sub(r"<[^>\n]*>", "", text)
    # stray directive/option lines that slipped through nesting
    text = re.sub(r"^(\s*)\.\.\s+(?:image|figure|thumbnail)::.*$", "", text, flags=re.M)
    text = re.sub(r"^(\s*)(?:replace|image|figure)::\s*.*$", "", text, flags=re.M)
    text = re.sub(r"\.\.\s+rst-class::[^\n]*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _emit_content(content, out):
    """Recursively render nested directive content."""
    sub = render_rst("\n".join(content))
    if sub:
        out.extend(sub.split("\n"))


def _emit_directive(dname, darg, content, out):
    d = dname.lower()
    if d in SKIP_DIRECTIVES or d == "replace":
        return
    if d in ("code", "code-block", "sourcecode"):
        if content:
            out.append("~~~")
            out.extend(c for c in content)
            out.append("~~~")
        return
    if d == "tab":
        if darg:
            out.append("### " + _clean_inline(darg))
        _emit_content(content, out)
        return
    if d in ("tabs", "tab-set"):
        _render_tabs(content, out)
        return
    if d == "dropdown":
        if darg:
            out.append("### " + _clean_inline(darg))
        _emit_content(content, out)
        return
    if d in ("list-table", "csv-table"):
        _render_list_table(content, out)
        return
    if d in ADMONITIONS:
        out.append("**%s:**" % ADMONITIONS[d])
        _emit_content(content, out)
        return
    # container-ish directives: keep content, drop the CSS class argument
    if d in ("div", "span", "container", "card", "h:div", "h:section"):
        _emit_content(content, out)
        return
    # admonition / rubric: emit title as heading + content
    if d in ("admonition", "rubric"):
        if darg:
            out.append("### " + _clean_inline(darg))
        _emit_content(content, out)
        return
    # generic directive: emit argument + content
    if darg:
        out.append(_clean_inline(darg))
    _emit_content(content, out)


def _render_tabs(content, out):
    for raw in content:
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"^\.\.\s+tab::\s*(.*)$", s)
        if m:
            if m.group(1).strip():
                out.append("### " + _clean_inline(m.group(1).strip()))
            continue
        if s.startswith(".. image") or s.startswith(":alt:") or s.startswith(":scale:") or s.startswith(":width:") or s.startswith(":height:") or s.startswith(":align:") or s.startswith(":class:") or s.startswith(":name:"):
            continue
        if s.startswith(".."):
            continue
        out.append(_clean_inline(s))


# ---------------------------------------------------------------- chunking

# Adaptive guide count per module: light modules collapse to a couple of guides,
# heavy modules split into many. Keeps the total in ~85 so the retriever's
# keyword list stays short while heavy modules stay finely navigable.


def target_guide_count(total_chars):
    if total_chars < 150_000:
        return 2
    if total_chars < 400_000:
        return 6
    if total_chars < 800_000:
        return 10
    return 14


def extract_file(path):
    with open(path, encoding="utf-8") as f:
        return render_rst(f.read())


def collect_module(applications_dir, module_slug):
    root = os.path.join(applications_dir, module_slug)
    groups = {}  # group_slug -> list of (title, text)
    top_files = []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if name.endswith(".rst"):
            top_files.append((name, p))
        elif os.path.isdir(p):
            fs = sorted(
                os.path.join(dp, fn)
                for dp, _, fns in os.walk(p)
                for fn in fns if fn.endswith(".rst")
            )
            if fs:
                groups[name] = fs
    # top-level rst files = root group (index + any loose content)
    if top_files:
        groups["__root__"] = [p for _, p in top_files]
    return groups


def first_paragraph(text):
    for para in text.split("\n\n"):
        p = " ".join(para.split())
        if p and not p.startswith("#") and not p.startswith("-") and not p.startswith("|"):
            return p
    return ""


def summarize(text, limit=220):
    p = first_paragraph(text)
    if not p:
        return ""
    if len(p) > limit:
        p = p[:limit].rstrip() + "..."
    return p


SPLIT_UNIT = 50000  # pre-split a single file into sections no larger than this


def split_long_text(text, limit=SPLIT_UNIT):
    """Split a large rendered text into sections at heading boundaries."""
    if len(text) <= limit:
        return [text]
    parts, cur, cur_len = [], [], 0
    for line in text.split("\n"):
        if line.startswith("#") and cur_len >= limit:
            parts.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        parts.append("\n".join(cur))
    # hard-split any section still over the limit (no headings to break on)
    final = []
    for p in parts:
        while len(p) > limit:
            final.append(p[:limit])
            p = p[limit:]
        if p:
            final.append(p)
    return final


def build_guides(applications_dir, module_slug, module_title):
    groups = collect_module(applications_dir, module_slug)
    # extract per file, pre-splitting oversized files into ~SPLIT_UNIT sections
    file_units = []  # (group_slug, text, size)
    for gslug, paths in groups.items():
        for p in paths:
            text = extract_file(p)
            if not text:
                continue
            for part in split_long_text(text):
                if part.strip():
                    file_units.append((gslug, part, len(part)))

    total = sum(u[2] for u in file_units)
    if total == 0:
        return []

    target = target_guide_count(total)
    if target == 1 or len(file_units) <= 1:
        body = "\n\n".join(u[1] for u in file_units)
        return [make_guide(module_slug, module_title, body, module_slug)]

    # group sections by sub-app (preserve order within group)
    from collections import OrderedDict
    ordered = OrderedDict()
    for gslug, text, size in file_units:
        ordered.setdefault(gslug, []).append((text, size))

    gsizes = {g: sum(sz for _, sz in units) for g, units in ordered.items()}

    # assign a guide count per group: proportional to size, floor 1, and a hard
    # cap so no guide exceeds ~CAP chars (ceil). Nudge to hit `target` where the
    # cap allows.
    CAP = 70000
    counts = {}
    for g, sz in gsizes.items():
        floor = max(1, -(-sz // CAP))          # ceil(sz / CAP)
        counts[g] = max(floor, int(sz / total * target))
    while sum(counts.values()) < target:
        g = max(counts, key=lambda x: gsizes[x] / (counts[x] + 1))
        counts[g] += 1
    while sum(counts.values()) > target:
        candidates = [x for x in counts if counts[x] > max(1, -(-gsizes[x] // CAP))]
        if not candidates:
            break
        g = max(candidates, key=lambda x: counts[x])
        counts[g] -= 1

    guides = []
    keyword_used = False
    for gslug, units in ordered.items():
        gtitle = module_title if gslug == "__root__" else "%s — %s" % (module_title, slug_title(gslug))
        base_code = module_slug if gslug == "__root__" else "%s-%s" % (module_slug, gslug)
        c = counts[gslug]
        if c == 1:
            body = "\n\n".join(text for text, _ in units)
            kw = module_slug if not keyword_used else ""
            keyword_used = True
            guides.append(make_guide(base_code, gtitle, body, kw))
        else:
            per = -(-gsizes[gslug] // c)
            chunk, size_acc = [], 0
            idx = 1
            for k, (text, sz) in enumerate(units):
                chunk.append(text)
                size_acc += sz
                if size_acc >= per or k == len(units) - 1:
                    body = "\n\n".join(chunk)
                    code = "%s-%d" % (base_code, idx)
                    title = "%s (part %d of %d)" % (gtitle, idx, c)
                    kw = module_slug if not keyword_used else ""
                    keyword_used = True
                    guides.append(make_guide(code, title, body, kw))
                    chunk, size_acc = [], 0
                    idx += 1
    return guides


def make_guide(code, title, body, keyword):
    return {
        "code": code,
        "title": title,
        "keyword": keyword,
        "summary": summarize(body),
        "body": body,
    }


def build_all_guides(applications_dir):
    """Build guide dicts for every application module under ``applications_dir``."""
    all_guides = []
    for slug, title in MODULES:
        all_guides.extend(build_guides(applications_dir, slug, title))
    return all_guides
