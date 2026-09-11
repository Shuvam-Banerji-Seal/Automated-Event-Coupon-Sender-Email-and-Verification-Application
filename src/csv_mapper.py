"""
CSV inspection and column-role detection.

An uploaded attendee sheet never has the columns this system wants. It has
"Email Address", "Timestamp", "Your Name", "Veg / Non-Veg?", "Roll No" — whatever
the form that produced it happened to emit. This module reads such a file and
proposes which column plays which role, so the operator confirms a guess instead
of describing the file from scratch.

Detection looks at two things and combines them:

* the header text, matched against known aliases, and
* the actual values, which is what settles the ambiguous cases. A column headed
  "Contact" holding ``a@b.com`` is an email column no matter what it is called,
  and header text alone would never tell you that.

Value evidence outranks header evidence, because headers lie more often than data
does.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^[\d\s+()-]{7,18}$")
BOOLISH = {
    "true", "false", "yes", "no", "y", "n", "1", "0", "on", "off",
    "TRUE", "FALSE",
}
VEG_WORDS = {
    "veg", "vegetarian", "non-veg", "nonveg", "non veg", "non-vegetarian",
    "nonvegetarian", "non vegetarian", "vegan", "eggetarian", "egg",
    "chicken", "jain",
}

# Roles the application understands. `required` ones block the import.
ROLES: Dict[str, Dict[str, Any]] = {
    "email": {
        "label": "Email address",
        "required": True,
        "help": "Where the invitation is sent. Must be unique per person.",
    },
    "name": {
        "label": "Full name",
        "required": False,
        "help": "Used for the greeting and shown on the scanner when they arrive.",
    },
    "food_preference": {
        "label": "Food preference",
        "required": False,
        "help": "Veg / non-veg. Drives the colour of the badge the scanner shows.",
    },
    "include_qr": {
        "label": "Gets an entry pass",
        "required": False,
        "help": "If false, the person is invited but issued no scannable coupon.",
    },
}

HEADER_ALIASES: Dict[str, Sequence[str]] = {
    "email": (
        "email", "e-mail", "email address", "emailaddress", "mail", "mail id",
        "email id", "emailid", "e mail", "institute email", "official email",
        "your email", "email address ", "contact email",
    ),
    "name": (
        "name", "full name", "fullname", "your name", "student name",
        "attendee name", "participant name", "first name", "display name",
    ),
    "food_preference": (
        "food preference", "food", "foodpreference", "food_pref", "food pref",
        "veg", "veg/non-veg", "veg / non-veg", "veg or non veg", "diet",
        "dietary preference", "dietary", "meal", "meal preference",
        "preference", "food choice", "meal choice", "veg/nonveg",
    ),
    "include_qr": (
        "include_qr", "include qr", "qr", "entry pass", "gets pass", "coupon",
        "dinner", "include_dinner", "attending dinner", "gala",
    ),
}

# Headers that are never a useful role, however they score.
NOISE_HEADERS = {"timestamp", "submitted at", "id", "sr no", "s.no", "serial"}


@dataclass
class ColumnProfile:
    """What one column looks like, and what it might be."""

    name: str
    index: int
    samples: List[str] = field(default_factory=list)
    non_empty: int = 0
    total: int = 0
    unique: int = 0
    scores: Dict[str, float] = field(default_factory=dict)

    @property
    def fill_rate(self) -> float:
        return self.non_empty / self.total if self.total else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "index": self.index,
            "samples": self.samples[:5],
            "non_empty": self.non_empty,
            "total": self.total,
            "unique": self.unique,
            "fill_rate": round(self.fill_rate, 3),
            "scores": {k: round(v, 3) for k, v in self.scores.items()},
        }


def _normalise_header(header: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (header or "").strip().lower()).strip()


def _header_score(header: str, role: str) -> float:
    """How much the column's name suggests a role. 0.0 - 1.0."""
    norm = _normalise_header(header)
    if not norm:
        return 0.0
    aliases = HEADER_ALIASES.get(role, ())
    if norm in aliases:
        return 1.0
    for alias in aliases:
        if norm.startswith(alias) or alias in norm:
            # "Email Address (institute)" still reads as an email column.
            return 0.75
    return 0.0


def _value_score(values: Sequence[str], role: str) -> float:
    """How much the column's contents suggest a role. 0.0 - 1.0."""
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return 0.0
    n = len(vals)

    if role == "email":
        return sum(1 for v in vals if EMAIL_RE.match(v)) / n

    if role == "food_preference":
        hits = 0
        for v in vals:
            low = v.lower().strip()
            if low in VEG_WORDS or any(w in low for w in ("veg", "vegan", "jain")):
                hits += 1
        ratio = hits / n
        # A real food column holds a short label from a tiny set of options. A
        # free-text comments field that happens to contain the word "veg" must
        # not win the role, so score it on shape as well as content: few
        # distinct values, and values that are short.
        distinct_penalty = 1.0 if len(set(v.lower() for v in vals)) <= 6 else 0.4
        avg_words = sum(len(v.split()) for v in vals) / n
        avg_chars = sum(len(v) for v in vals) / n
        if avg_words > 4 or avg_chars > 24:
            length_penalty = 0.1
        elif avg_words > 2.5 or avg_chars > 16:
            length_penalty = 0.5
        else:
            length_penalty = 1.0
        return ratio * distinct_penalty * length_penalty

    if role == "include_qr":
        boolish = sum(1 for v in vals if v.strip().lower() in BOOLISH) / n
        return boolish if len(set(v.lower() for v in vals)) <= 3 else boolish * 0.5

    if role == "name":
        # Names: mostly alphabetic, usually 1-4 words, rarely repeated, and
        # definitely not email addresses or numbers.
        if sum(1 for v in vals if EMAIL_RE.match(v)) / n > 0.3:
            return 0.0
        looks_like = 0
        for v in vals:
            words = v.split()
            if not (1 <= len(words) <= 5):
                continue
            letters = sum(c.isalpha() or c.isspace() or c in ".'-" for c in v)
            if len(v) and letters / len(v) > 0.85 and not v.isdigit():
                looks_like += 1
        ratio = looks_like / n
        uniqueness = len(set(vals)) / n
        return ratio * (0.5 + 0.5 * uniqueness)

    return 0.0


def profile_columns(headers: Sequence[str], rows: Sequence[Dict[str, str]]) -> List[ColumnProfile]:
    """Build a profile, with role scores, for every column in the sheet."""
    profiles: List[ColumnProfile] = []
    for idx, header in enumerate(headers):
        values = [str(r.get(header, "") or "") for r in rows]
        non_empty = [v for v in values if v.strip()]
        profile = ColumnProfile(
            name=header,
            index=idx,
            samples=non_empty[:5],
            non_empty=len(non_empty),
            total=len(values),
            unique=len(set(non_empty)),
        )
        is_noise = _normalise_header(header) in NOISE_HEADERS
        for role in ROLES:
            if is_noise:
                profile.scores[role] = 0.0
                continue
            head = _header_score(header, role)
            body = _value_score(non_empty, role)
            # Values dominate; the header breaks ties and rescues sparse columns.
            profile.scores[role] = round(0.35 * head + 0.65 * body, 4)
        profiles.append(profile)
    return profiles


def suggest_mapping(profiles: Sequence[ColumnProfile]) -> Dict[str, Optional[str]]:
    """Pick the best column for each role, never assigning one column twice.

    Roles are resolved strongest-match-first across the whole grid rather than
    role-by-role, so a column that is an excellent email match is not consumed by
    a weaker role that merely happened to be considered earlier.
    """
    candidates: List[Tuple[float, str, str]] = []
    for profile in profiles:
        for role, score in profile.scores.items():
            if score >= 0.35:
                candidates.append((score, role, profile.name))
    candidates.sort(reverse=True)

    mapping: Dict[str, Optional[str]] = {role: None for role in ROLES}
    taken: set = set()
    for score, role, column in candidates:
        if mapping[role] is None and column not in taken:
            mapping[role] = column
            taken.add(column)
    return mapping


def read_csv_bytes(raw: bytes) -> Tuple[List[str], List[Dict[str, str]], str]:
    """Decode and parse an uploaded file, coping with the usual real-world mess.

    Handles UTF-8 with or without BOM, falls back to latin-1 rather than failing,
    and sniffs the delimiter so semicolon- and tab-separated exports work too.
    """
    # UTF-16 is only attempted when a byte-order mark actually says so. Tried
    # speculatively it is worse than useless: almost any byte sequence of even
    # length "decodes" into plausible-looking CJK, so a merely corrupt UTF-8
    # file would be silently accepted as gibberish instead of falling through
    # to the latin-1 fallback.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16", "utf-8-sig", "utf-8", "latin-1")
    else:
        encodings = ("utf-8-sig", "utf-8", "latin-1")

    text = None
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sample = text[:8192]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    raw_headers = reader.fieldnames or []

    # Blank and duplicate headers break DictReader consumers downstream.
    headers: List[str] = []
    seen: Dict[str, int] = {}
    for i, h in enumerate(raw_headers):
        name = (h or "").strip() or f"column_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        headers.append(name)

    rows: List[Dict[str, str]] = []
    for record in reader:
        row: Dict[str, str] = {}
        for original, clean in zip(raw_headers, headers):
            value = record.get(original, "")
            row[clean] = "" if value is None else str(value).strip()
        if any(v for v in row.values()):
            rows.append(row)
    return headers, rows, delimiter


def inspect(raw: bytes) -> Dict[str, Any]:
    """Full inspection result handed to the mapping UI."""
    headers, rows, delimiter = read_csv_bytes(raw)
    profiles = profile_columns(headers, rows)
    mapping = suggest_mapping(profiles)

    emails_seen: Dict[str, int] = {}
    email_col = mapping.get("email")
    invalid_emails, duplicate_emails = [], []
    if email_col:
        for i, row in enumerate(rows, start=2):
            value = (row.get(email_col) or "").strip().lower()
            if not value:
                invalid_emails.append({"row": i, "value": "", "reason": "empty"})
            elif not EMAIL_RE.match(value):
                invalid_emails.append({"row": i, "value": value, "reason": "malformed"})
            else:
                if value in emails_seen:
                    duplicate_emails.append(
                        {"row": i, "value": value, "first_seen": emails_seen[value]}
                    )
                else:
                    emails_seen[value] = i

    return {
        "headers": headers,
        "delimiter": delimiter,
        "row_count": len(rows),
        "columns": [p.to_dict() for p in profiles],
        "suggested_mapping": mapping,
        "roles": ROLES,
        "preview": rows[:25],
        "validation": {
            "valid_emails": len(emails_seen),
            "invalid": invalid_emails[:50],
            "invalid_count": len(invalid_emails),
            "duplicates": duplicate_emails[:50],
            "duplicate_count": len(duplicate_emails),
        },
    }


def build_recipients(
    rows: Sequence[Dict[str, str]],
    mapping: Dict[str, Optional[str]],
    keep_extra: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply a confirmed mapping, returning (accepted, rejected).

    Extra columns are preserved verbatim so they stay available as template
    variables — that "Roll No" column nobody mapped is still something the
    operator may want to print on the invitation.
    """
    from src.store import as_bool, normalise_food

    email_col = mapping.get("email")
    name_col = mapping.get("name")
    food_col = mapping.get("food_preference")
    qr_col = mapping.get("include_qr")
    mapped_cols = {c for c in (email_col, name_col, food_col, qr_col) if c}

    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    seen: set = set()

    for i, row in enumerate(rows, start=2):
        email = (row.get(email_col, "") if email_col else "").strip().lower()
        if not email:
            rejected.append({"row": i, "email": "", "reason": "no email"})
            continue
        if not EMAIL_RE.match(email):
            rejected.append({"row": i, "email": email, "reason": "malformed email"})
            continue
        if email in seen:
            rejected.append({"row": i, "email": email, "reason": "duplicate in file"})
            continue
        seen.add(email)

        extra = {}
        if keep_extra:
            for key, value in row.items():
                if key not in mapped_cols and value != "":
                    # Make the key usable as a Jinja identifier.
                    safe = re.sub(r"\W+", "_", key.strip().lower()).strip("_")
                    if safe and safe not in ("email", "name", "first_name"):
                        extra[safe] = value

        accepted.append(
            {
                "email": email,
                "name": (row.get(name_col, "") if name_col else "").strip(),
                "food_preference": normalise_food(
                    row.get(food_col) if food_col else None
                ),
                "include_qr": as_bool(row.get(qr_col) if qr_col else None, True),
                "extra": extra,
            }
        )
    return accepted, rejected
