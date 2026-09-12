"""The answer bank, read from config/application-answers.md at run time.

Every screening answer the pipeline gives comes from that file, parsed here.
Nothing in this module invents a value: if the file lacks a field the caller
gets None and must apply section L (log a gap, or skip the job). Edit the
markdown and the next run uses the edit.

    import answers
    bank = answers.load()          # {"A": {"Minimum base salary": "$50,000", ...}, ...}
    answers.get(bank, "A", "Desired salary")   # fuzzy field lookup within a section
"""

import re

import db

PATH = db.BASE_DIR / "config" / "application-answers.md"

_SECTION_RX = re.compile(r"^## ([A-Z])\. (.+)$")
_ROW_RX = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$")


def load(path=None):
    path = path or PATH
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing — copy config/application-answers.example.md to "
            "config/application-answers.md and fill in YOUR truthful answers "
            "(they are attestations on signed forms)")
    bank = {"_titles": {}, "_notes": {}}
    section = None
    for line in path.read_text().splitlines():
        m = _SECTION_RX.match(line.strip())
        if m:
            section = m.group(1)
            bank[section] = {}
            bank["_titles"][section] = m.group(2).strip()
            continue
        if section is None:
            # the un-lettered identity block at the top: the work-authorization
            # line plus table rows (voluntary self-identification answers)
            if line.lower().startswith("work authorization:"):
                bank.setdefault("ID", {})["Work authorization"] = line.split(":", 1)[1].strip()
                continue
            m = _ROW_RX.match(line.strip())
            if m and m.group(1).lower() not in ("field", ":----", ":-----", "----") and not set(m.group(1)) <= set(":- "):
                field = m.group(1).replace("**", "").strip().strip('"')
                answer = m.group(2).replace("**", "").strip()
                bank.setdefault("ID", {})[field] = answer.replace("<br>", "\n")
            continue
        m = _ROW_RX.match(line.strip())
        if m and m.group(1).lower() not in ("field", ":----", ":-----", "----"):
            field, answer = m.group(1), m.group(2)
            if set(field) <= set(":- "):
                continue
            field = field.replace("**", "").strip().strip('"')
            answer = answer.replace("**", "").strip()
            bank[section][field] = answer.replace("<br>", "\n")   # <br> = paragraph break in an essay answer
    return bank


def get(bank, section, field):
    """Exact, then case-insensitive substring match on the field name."""
    sec = bank.get(section, {})
    if field in sec:
        return sec[field]
    f = field.lower()
    for k, v in sec.items():
        if f in k.lower() or k.lower() in f:
            return v
    return None


def _label_norm(s):
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).split()


def find_by_label(bank, label, sections="BCEHKM"):
    """The answer whose *field text* is the form's own label: exact after
    normalisation, or (for labels of 8+ words) the stored field contained in
    the label, so a question that arrived through the chat gap flow answers
    the same form next time. Attestation sections (A salary, D experience,
    F clearance) are excluded on purpose: those map only through the
    explicit rules. Returns (value, section) or (None, None)."""
    want = _label_norm(label)
    if not want:
        return None, None
    wj = " ".join(want)
    for sec in sections:
        for field, val in bank.get(sec, {}).items():
            fj = " ".join(_label_norm(field))
            if fj and (fj == wj or (len(want) >= 8 and len(fj.split()) >= 6 and fj in wj)):
                return val, sec
    return None, None


# Set this to your own current employer so a posting from them gets a truthful
# "Yes" for "previously employed here". The example applicant works at BitBench.
CURRENT_EMPLOYER_RX = re.compile(r"bitbench", re.I)

def previously_employed(bank, company):
    """§E 'Previously employed here' is a plain 'No' in the file. The one
    exception is the operator's current employer: on a req from them the
    truthful answer is 'Yes'. That rule lives here, in code, so the
    answer file never carries instructions."""
    if CURRENT_EMPLOYER_RX.search(company or ""):
        return "Yes", "current employer; answer file §E default is No"
    return get(bank, "E", "Previously employed here"), "answer file §E"


# ---------------------------------------------------------------------------
# Writer — the chat agent's update_answer_bank lands here (after the operator
# confirms). It appends one table row to a section; it never edits or removes
# an existing row, so every prior attestation stays exactly as written.
# ---------------------------------------------------------------------------

CHAT_SECTION = ("M", "Answers added from chat")


def _section_bounds(lines):
    """{letter: line index of its '## X. Title' header}."""
    heads = {}
    for i, line in enumerate(lines):
        m = _SECTION_RX.match(line.strip())
        if m:
            heads[m.group(1)] = i
    return heads


def update_row(section, field, answer, path=None):
    """Replace the answer cell of an existing `| field | answer |` row.

    The dashboard's Answers page edits land here (the operator acting on
    their own file; the chat agent still only appends via append_row).
    Field match is exact after stripping bold markers and outer quotes,
    case-insensitive. The field cell is kept verbatim — bold markers and
    wording stay exactly as written. Returns the 1-based line number.
    Raises KeyError when the section or row is absent.
    """
    path = path or PATH
    answer = " ".join(str(answer).replace("|", "/").split())
    if not answer:
        raise ValueError("answer is required")
    lines = path.read_text().splitlines()
    heads = _section_bounds(lines)
    section = (section or "").strip().upper()[:2]
    want = str(field).replace("**", "").strip().strip('"').lower()
    if section == "ID":
        start, end = 0, min(heads.values()) if heads else len(lines)
    else:
        section = section[:1]
        if section not in heads:
            raise KeyError(f"no section {section!r} in the answer file")
        start = heads[section]
        end = min([i for i in heads.values() if i > start] + [len(lines)])
    for i in range(start, end):
        m = _ROW_RX.match(lines[i].strip())
        if not m:
            continue
        cell = m.group(1)
        if set(cell) <= set(":- ") or cell.lower() == "field":
            continue
        if cell.replace("**", "").strip().strip('"').lower() == want:
            lines[i] = f"| {cell} | {answer} |"
            path.write_text("\n".join(lines) + "\n")
            return i + 1
    raise KeyError(f"no row {field!r} in section {section}")


def append_row(section, field, answer, path=None):
    """Append `| field | answer |` to the table in section `section` (a letter).
    Unknown section letter -> the row goes under section M, created on first
    use. Returns (section_used, line_number). Pipes and newlines in the values
    are replaced so the markdown table stays parseable."""
    path = path or PATH
    clean = lambda v: " ".join(str(v).replace("|", "/").split())
    field, answer = clean(field), clean(answer)
    if not field or not answer:
        raise ValueError("field and answer are both required")
    lines = path.read_text().splitlines()
    heads = {}
    for i, line in enumerate(lines):
        m = _SECTION_RX.match(line.strip())
        if m:
            heads[m.group(1)] = i
    section = (section or "").strip().upper()[:1]
    if section not in heads or section == "L":          # L is the rule, not a table
        section = CHAT_SECTION[0]
        if section not in heads:
            lines += ["", "---", "", f"## {CHAT_SECTION[0]}. {CHAT_SECTION[1]}", "",
                      "Rows appended by the chat agent after operator confirmation. "
                      "Each one closes an answer gap; edit freely.", "",
                      "| Field | Answer |", "| :---- | :---- |"]
            heads[section] = len(lines) - 5
    start = heads[section]
    end = min([i for i in heads.values() if i > start] + [len(lines)])
    last_row = None
    for i in range(start, end):
        if _ROW_RX.match(lines[i].strip()):
            last_row = i
    if last_row is None:
        # a section without a table yet: add one right after the header
        lines[start + 1:start + 1] = ["", "| Field | Answer |", "| :---- | :---- |"]
        last_row = start + 3
    lines.insert(last_row + 1, f"| {field} | {answer} |")
    path.write_text("\n".join(lines) + "\n")
    return section, last_row + 2
