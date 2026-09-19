"""
Email template rendering, variable discovery and validation.

Templates are authored in the browser and stored in the database, so they are
rendered from strings rather than files. That means arbitrary template source
reaches Jinja, and a plain ``Environment`` would let a template reach through
Python objects into the process. Everything here goes through a
``SandboxedEnvironment``.

The other job of this module is telling the UI *which* variables a template may
use, assembled from three places: fixed system fields, the event settings, and
whatever extra columns survived the last CSV upload.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from jinja2 import TemplateSyntaxError, meta
from jinja2.sandbox import SandboxedEnvironment

from src.store import first_name, food_colour, normalise_food

_env = SandboxedEnvironment(autoescape=True, trim_blocks=False, lstrip_blocks=False)

# Subject lines are not HTML. Rendering them through the autoescaping
# environment turns an apostrophe in the event name into "&#39;", which then
# appears literally in the recipient's inbox — "Freshers&#39; Welcome". Subjects
# get their own environment with escaping off; they are still sandboxed, and
# render_subject() collapses them to a single line so header injection via a
# newline is not possible.
_subject_env = SandboxedEnvironment(autoescape=False)


class TemplateError(Exception):
    """A template failed to parse or render, with a message fit for the UI."""


# Variables the system always provides, grouped for presentation in the editor.
SYSTEM_VARIABLES: Dict[str, List[Dict[str, str]]] = {
    "Attendee": [
        {"name": "name", "desc": "Full name as it appeared in the CSV", "sample": "Ada Lovelace"},
        {"name": "first_name", "desc": "First word of the name — for greetings", "sample": "Ada"},
        {"name": "email", "desc": "Their email address", "sample": "ada@iiserkol.ac.in"},
        {"name": "food_preference", "desc": "Vegetarian or Non-Vegetarian", "sample": "Vegetarian"},
        {"name": "food_colour", "desc": "Badge colour matching the preference", "sample": "#1f8a4c"},
        {"name": "include_qr", "desc": "True if this person gets an entry pass", "sample": "True"},
    ],
    "Coupon": [
        {"name": "verification_code", "desc": "The 6-digit code, also encoded in the QR", "sample": "418206"},
        {"name": "coupon_id", "desc": "Internal unique id", "sample": "3f2a…"},
        {"name": "qr_code_src", "desc": "Image source for the QR — use inside <img src=\"…\">", "sample": "cid:qrcode"},
    ],
    "Meal passes": [
        {"name": "coupons", "desc": "Every pass this person holds — loop with {% for c in coupons %}", "sample": "4 passes"},
        {"name": "coupon_count", "desc": "How many passes are in this email", "sample": "4"},
        {"name": "c.meal_label", "desc": "Inside the loop: the sitting's name", "sample": "Day 1 · Lunch"},
        {"name": "c.date", "desc": "Inside the loop: the date it is served", "sample": "Tue, 22 Sep 2026"},
        {"name": "c.time", "desc": "Inside the loop: serving window", "sample": "13:10 – 14:25"},
        {"name": "c.venue", "desc": "Inside the loop: where it is served", "sample": "R.N. Tagore Auditorium"},
        {"name": "c.verification_code", "desc": "Inside the loop: that pass's 6-digit code", "sample": "418206"},
        {"name": "c.qr_code_src", "desc": "Inside the loop: that pass's QR image source", "sample": "cid:qr-d1-lunch"},
    ],
    "Thank-you mail": [
        {"name": "redeemed", "desc": "The sitting just collected — redeemed.meal_label, .time, .venue", "sample": "Day 1 · Lunch"},
        {"name": "checked_in_at", "desc": "When they were scanned, in the event's timezone", "sample": "13:22"},
        {"name": "remaining", "desc": "Passes they still hold — loop it to list what is left", "sample": "3 passes"},
        {"name": "remaining_count", "desc": "How many sittings are still ahead of them", "sample": "3"},
        {"name": "next_pass", "desc": "The next one they hold, or nothing if that was the last", "sample": "Day 1 · Dinner"},
    ],
    "Event": [
        {"name": "event_name", "desc": "Name of the event", "sample": "Farewell Party 2026"},
        {"name": "event_date", "desc": "Date as configured in settings", "sample": "15 May 2026"},
        {"name": "event_time", "desc": "Start time", "sample": "5:30 PM"},
        {"name": "event_venue", "desc": "Where it happens", "sample": "Rabindranath Tagore Auditorium"},
        {"name": "organizer_batch", "desc": "Organising batch", "sample": "22MS Batch"},
        {"name": "organizer_institution", "desc": "Institution", "sample": "IISER Kolkata"},
    ],
}


def variable_catalogue(
    extra_columns: Sequence[str] = (), settings: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """Everything the editor can offer, grouped and ready to render as chips."""
    groups: List[Dict[str, Any]] = []
    for group, entries in SYSTEM_VARIABLES.items():
        groups.append({"group": group, "variables": [dict(e) for e in entries]})

    known = {
        v["name"] for g in SYSTEM_VARIABLES.values() for v in g
    }
    custom = [c for c in extra_columns if c not in known]
    if custom:
        groups.append(
            {
                "group": "From your CSV",
                "variables": [
                    {
                        "name": c,
                        "desc": "Extra column preserved from the uploaded sheet",
                        "sample": "",
                    }
                    for c in custom
                ],
            }
        )
    return groups


def qr_cid(meal_key: str) -> str:
    """The Content-ID a pass's QR is attached under.

    One name per sitting, because a four-meal email carries four distinct
    images. Single-sitting events keep the historical ``qrcode``, so templates
    written before meal passes go on working untouched.
    """
    return f"qr-{meal_key}" if meal_key else "qrcode"


def build_context(
    *,
    name: str = "",
    email: str = "",
    food_preference: str = "Vegetarian",
    include_qr: bool = True,
    verification_code: str = "",
    coupon_id: str = "",
    qr_code_src: str = "cid:qrcode",
    coupons: Optional[Sequence[Dict[str, Any]]] = None,
    redeemed: Optional[Dict[str, Any]] = None,
    remaining: Optional[Sequence[Dict[str, Any]]] = None,
    checked_in_at: str = "",
    extra: Optional[Dict[str, Any]] = None,
    settings: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Assemble the render context for one recipient.

    Extras go in first so a mapped field always wins over a stray CSV column of
    the same name — a sheet with its own "email" column must not be able to
    redirect where the invitation is addressed.

    ``coupons`` is every pass the person holds, in serving order, so a
    multi-meal conference is one email with a loop rather than one email per
    meal. The flat ``verification_code``/``qr_code_src`` pair keeps describing
    the first pass, which is what a single-sitting event has always meant.

    ``redeemed`` and ``remaining`` are what a thank-you is written around: the
    sitting somebody just collected, and the ones they still hold. Without them
    a thank-you can only say "thanks for coming", which is worth nothing on the
    first of four meals.
    """
    food = normalise_food(food_preference)
    passes = [dict(c) for c in (coupons or [])]
    still_held = [dict(c) for c in (remaining or [])]
    context: Dict[str, Any] = dict(extra or {})
    context.update(
        {
            "name": name,
            "first_name": first_name(name, email),
            "email": email,
            "food_preference": food,
            "food_colour": food_colour(food),
            "food_color": food_colour(food),  # US spelling kept as an alias
            "include_qr": include_qr,
            "verification_code": verification_code,
            "coupon_id": coupon_id,
            "qr_code_src": qr_code_src if include_qr else "",
            "coupons": passes,
            "coupon_count": len(passes),
            "redeemed": dict(redeemed) if redeemed else None,
            "remaining": still_held,
            "remaining_count": len(still_held),
            "next_pass": still_held[0] if still_held else None,
            "checked_in_at": checked_in_at,
            # Long-standing aliases from earlier templates, kept so existing
            # saved templates keep rendering after the upgrade.
            "attendee_name": name,
            "attendee_email": email,
        }
    )
    for key, value in (settings or {}).items():
        context.setdefault(key, value)
    return context


def coupon_context(
    coupon: Any, session: Any = None, qr_code_src: str = ""
) -> Dict[str, Any]:
    """One entry of the ``coupons`` list, as a template sees it.

    Serving details come from the session settings when the sitting still
    exists, and fall back to the label frozen onto the coupon row when it does
    not — a pass already in somebody's inbox must keep describing itself even
    after the organisers edit the schedule.
    """
    food = normalise_food(getattr(coupon, "food_preference", ""))
    return {
        "meal_key": coupon.meal_key,
        "meal_label": (
            getattr(session, "label", "") or coupon.meal_label or coupon.meal_key
        ),
        "day": getattr(session, "day", ""),
        "meal": getattr(session, "meal", ""),
        "date": getattr(session, "date", ""),
        "time": getattr(session, "time", ""),
        "venue": getattr(session, "venue", ""),
        "verification_code": coupon.verification_code,
        "coupon_id": coupon.coupon_id,
        "qr_code_src": qr_code_src or f"cid:{qr_cid(coupon.meal_key)}",
        "food_preference": food,
        "food_colour": food_colour(food),
        "status": getattr(coupon, "status", ""),
    }


# What the preview shows when no sittings are configured: one plain pass, so the
# editor still exercises the {% for %} loop an ICOC-style template is built on.
_SAMPLE_SESSIONS = [
    {"meal_key": "", "meal_label": "Entry pass", "day": "", "meal": "",
     "date": "", "time": "", "venue": ""},
]


def sample_context(
    settings: Optional[Dict[str, str]] = None,
    extra_columns: Sequence[str] = (),
    food_preference: str = "Vegetarian",
    sessions: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """A realistic context for previewing a template with no real recipient."""
    extra = {c: f"‹{c}›" for c in extra_columns}
    food = normalise_food(food_preference)
    entries = []
    for index, session in enumerate(sessions or []):
        entries.append(
            {
                "meal_key": session.key,
                "meal_label": session.label,
                "day": session.day,
                "meal": session.meal,
                "date": session.date,
                "time": session.time,
                "venue": session.venue,
                "verification_code": f"{418206 + index * 1117:06d}",
                "coupon_id": f"preview-{index:04d}",
                "qr_code_src": "{{QR_PREVIEW}}",
                "food_preference": food,
                "food_colour": food_colour(food),
                "status": "sent",
            }
        )
    if not entries:
        entries = [
            {
                **_SAMPLE_SESSIONS[0],
                "verification_code": "418206",
                "coupon_id": "preview-0000",
                "qr_code_src": "{{QR_PREVIEW}}",
                "food_preference": food,
                "food_colour": food_colour(food),
                "status": "sent",
            }
        ]
    return build_context(
        name="Ada Lovelace",
        email="ada.lovelace@iiserkol.ac.in",
        food_preference=food_preference,
        include_qr=True,
        verification_code=entries[0]["verification_code"],
        coupon_id=entries[0]["coupon_id"],
        qr_code_src="{{QR_PREVIEW}}",
        coupons=entries,
        # Pretend the first sitting has just been collected, so a thank-you
        # template previews with something in `redeemed` and something left in
        # `remaining` — the two states it is written around.
        redeemed=entries[0],
        remaining=entries[1:],
        checked_in_at="13:22",
        extra=extra,
        settings=settings,
    )


def render(source: str, context: Dict[str, Any]) -> str:
    """Render a template string, converting Jinja errors into readable ones."""
    try:
        return _env.from_string(source).render(**context)
    except TemplateSyntaxError as exc:
        raise TemplateError(f"Line {exc.lineno}: {exc.message}") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to the editor
        raise TemplateError(str(exc)) from exc


def render_subject(source: str, context: Dict[str, Any]) -> str:
    """Render a subject line: no HTML escaping, always one line.

    Collapsing whitespace is what keeps a newline in an event name from
    splitting the header and injecting one of its own.
    """
    try:
        rendered = _subject_env.from_string(source or "").render(**context)
    except TemplateSyntaxError as exc:
        raise TemplateError(f"Line {exc.lineno}: {exc.message}") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to the editor
        raise TemplateError(str(exc)) from exc
    return " ".join(rendered.split())


def used_variables(source: str) -> List[str]:
    """Variable names a template refers to."""
    try:
        ast = _env.parse(source)
    except TemplateSyntaxError:
        return []
    return sorted(meta.find_undeclared_variables(ast))


def validate(source: str, available: Iterable[str]) -> Dict[str, Any]:
    """Check a template parses, and flag variables nothing will supply.

    An unknown variable is a warning rather than an error: Jinja renders it as
    empty, which is survivable, but it is nearly always a typo and the operator
    should see it before a few hundred emails go out.
    """
    result: Dict[str, Any] = {"ok": True, "errors": [], "warnings": [], "used": []}
    try:
        _env.parse(source)
    except TemplateSyntaxError as exc:
        result["ok"] = False
        result["errors"].append(f"Line {exc.lineno}: {exc.message}")
        return result

    used = used_variables(source)
    result["used"] = used
    known = set(available)
    unknown = [v for v in used if v not in known]
    if unknown:
        result["warnings"].append(
            "Nothing will fill in: " + ", ".join(f"{{{{ {v} }}}}" for v in unknown)
        )
    return result


_IMG_SRC_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)


def lint_email_html(html: str) -> List[Dict[str, str]]:
    """Warn about HTML that renders badly in real mail clients.

    These are the failure modes this project has actually hit — inline SVG being
    stripped by the Gmail app cost a whole send cycle once — rather than a
    generic HTML validation pass.
    """
    issues: List[Dict[str, str]] = []
    low = html.lower()

    if "<svg" in low:
        issues.append(
            {
                "level": "error",
                "message": "Inline <svg> is stripped by Gmail, Outlook and most "
                "mobile clients. Use a PNG (a data: URI is fine) instead.",
            }
        )
    if "<script" in low:
        issues.append(
            {"level": "error", "message": "<script> is removed by every mail client."}
        )
    if "position:absolute" in low.replace(" ", "") or "position:fixed" in low.replace(" ", ""):
        issues.append(
            {
                "level": "warning",
                "message": "Absolute/fixed positioning is unsupported in Outlook. "
                "Lay out with tables or simple block elements.",
            }
        )
    if "display:flex" in low.replace(" ", "") or "display:grid" in low.replace(" ", ""):
        issues.append(
            {
                "level": "warning",
                "message": "Flexbox and grid are ignored by Outlook's rendering "
                "engine. Tables remain the reliable option for email layout.",
            }
        )
    if "<link" in low and "stylesheet" in low:
        issues.append(
            {
                "level": "warning",
                "message": "External stylesheets are not fetched by mail clients. "
                "Put styles in a <style> block or inline on the elements.",
            }
        )
    for src in _IMG_SRC_RE.findall(html):
        if src.startswith("http://"):
            issues.append(
                {
                    "level": "warning",
                    "message": f"Image loaded over plain http ({src[:60]}) — many "
                    "clients block it. Use https or embed the image.",
                }
            )
    if len(html.encode("utf-8")) > 102_400:
        issues.append(
            {
                "level": "warning",
                "message": "Over 100 KB: Gmail clips messages past ~102 KB and "
                "hides the rest behind a 'View entire message' link.",
            }
        )
    return issues
