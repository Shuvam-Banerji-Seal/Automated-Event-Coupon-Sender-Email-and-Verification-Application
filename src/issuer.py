"""
Coupon issuing and QR rendering.

Splits cleanly from persistence: this module decides what a coupon *is* and what
its QR looks like; ``src.store`` decides how it is kept. Nothing here writes to
disk except through the store handed in.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import uuid
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence

import qrcode
from qrcode.constants import ERROR_CORRECT_M, ERROR_CORRECT_Q

from src.encryption import EncryptionService
from src.store import (
    Coupon,
    CouponStore,
    MealSession,
    Recipient,
    normalise_food,
    qr_payload,
    utcnow,
)

logger = logging.getLogger(__name__)

_rng = secrets.SystemRandom()


class QRSizeError(ValueError):
    """Raised when a payload would produce a QR too dense to scan reliably."""


# A coupon QR is read off a phone screen by another phone, often a cracked one,
# at an angle, in a dim hall, by someone in a queue. The limiting factor is
# module size: the more data, the more modules in the same physical area, and
# below roughly 8 screen-pixels per module a cracked or smudged display stops
# decoding reliably.
#
# Our payload is fixed at 16 bytes, which is QR version 1 (21x21) even at
# error-correction Q. Version 2 gives generous headroom while still leaving
# ~9 px/module on a 300px image. Refusing anything denser means an accidental
# payload change cannot silently make every coupon at an event unscannable —
# it fails loudly here instead of quietly at the door.
MAX_QR_VERSION = 2


def make_qr_png(
    data: str,
    box_size: int = 12,
    border: int = 4,
    fill: str = "#000000",
    back: str = "#FFFFFF",
    error_correction: int = ERROR_CORRECT_Q,
) -> bytes:
    """Render ``data`` to a PNG, refusing payloads that are too dense.

    Error correction Q (~25% recovery) is affordable only because the payload is
    tiny: at 16 bytes it still fits QR version 1. Level L or M would not shrink
    the code any further, so there is no reason to accept the weaker recovery —
    and a scratched screen is exactly the failure mode at a door.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=error_correction,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)

    if qr.version > MAX_QR_VERSION:
        raise QRSizeError(
            f"QR payload needs version {qr.version} (max {MAX_QR_VERSION}). "
            f"The payload is {len(data)} bytes; keep it at or under ~20. "
            f"Look data up server-side from the token instead of packing it "
            f"into the code — a denser QR will not scan off a cracked screen."
        )

    img = qr.make_image(fill_color=fill, back_color=back)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def coupon_qr_png(coupon: Coupon, box_size: int = 12) -> bytes:
    """The scannable entry pass for one coupon."""
    return make_qr_png(coupon.qr_payload, box_size=box_size)


def make_link_qr(url: str, box_size: int = 8) -> bytes:
    """Render an arbitrary URL — used for the "open the scanner" QR.

    Deliberately not subject to MAX_QR_VERSION: a URL is far longer than a
    coupon payload, and this code is scanned once, at leisure, off a laptop
    screen rather than at a door off a cracked phone.
    """
    qr = qrcode.QRCode(
        version=None, error_correction=ERROR_CORRECT_M,
        box_size=box_size, border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    buffer = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def qr_data_uri(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode()


def describe_payload(qr_token: str) -> Dict[str, Any]:
    """Report how dense a coupon's QR is. Surfaced in the UI as a health check."""
    payload = qr_payload(qr_token)
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_Q, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    modules = qr.version * 4 + 17
    return {
        "payload": payload,
        "bytes": len(payload.encode("utf-8")),
        "version": qr.version,
        "modules": f"{modules}x{modules}",
        "within_limit": qr.version <= MAX_QR_VERSION,
        "max_version": MAX_QR_VERSION,
        "error_correction": "Q (~25% recoverable)",
        "px_per_module_at_300": round(300 / (modules + 8), 1),
    }


class CouponIssuer:
    """Creates coupons for recipients and hands back renderable records."""

    def __init__(self, store: CouponStore, secret_key: Optional[str] = None):
        self.store = store
        self.encryption = EncryptionService(secret_key)

    def issue_batch(
        self,
        recipients: Sequence[Recipient],
        event_name: str = "",
        skip_existing: bool = True,
        sessions: Optional[Sequence[MealSession]] = None,
    ) -> Dict[str, Any]:
        """Issue one coupon per recipient per sitting.

        Codes are reserved inside a single transaction so two concurrent batches
        cannot hand out the same six digits. A (person, sitting) pair that already
        holds a coupon is skipped by default — re-running a send must never mint a
        second coupon for someone and silently invalidate the code already in
        their inbox.

        With no sessions configured this issues exactly one coupon per recipient,
        carrying the empty meal key, which is what every single-sitting event
        before ICOC did.
        """
        if sessions is None:
            sessions = self.store.issuing_sessions()
        sessions = list(sessions) or [MealSession(key="", label="")]

        existing = self.store.existing_meal_pairs() if skip_existing else set()
        issued: List[Coupon] = []
        skipped: List[str] = []
        errors: List[Dict[str, str]] = []

        with self.store.write() as conn:
            for recipient in recipients:
                email = recipient.email.lower().strip()
                if not email:
                    errors.append({"email": "", "error": "empty email"})
                    continue
                for order, session in enumerate(sessions):
                    if (email, session.key) in existing:
                        skipped.append(email)
                        continue
                    try:
                        code = self.store.reserve_code(conn, _rng)
                        token = self.store.reserve_token(conn, _rng)
                        coupon_id = str(uuid.uuid4())
                        now = utcnow()
                        payload = {
                            "coupon_id": coupon_id,
                            "email": email,
                            "event_name": event_name,
                            "meal_key": session.key,
                            "verification_code": code,
                            "created_at": now,
                            "valid": True,
                        }
                        coupon = Coupon(
                            coupon_id=coupon_id,
                            email=email,
                            name=recipient.name,
                            verification_code=code,
                            qr_token=token,
                            food_preference=normalise_food(recipient.food_preference),
                            include_qr=recipient.include_qr,
                            status="generated",
                            event_name=event_name,
                            encrypted_data=self.encryption.encrypt_coupon_data(
                                payload, email
                            ),
                            created_at=now,
                            meal_key=session.key,
                            meal_label=session.label,
                            meal_order=order,
                            extra=dict(recipient.extra),
                        )
                        # Insert inside the same transaction that reserved the
                        # code, so the uniqueness check above cannot be raced.
                        conn.execute(
                            "INSERT INTO coupons"
                            "(coupon_id, email, name, verification_code, qr_token,"
                            " food_preference, include_qr, status, event_name,"
                            " encrypted_data, extra, meal_key, meal_label,"
                            " meal_order, created_at)"
                            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                coupon.coupon_id,
                                coupon.email,
                                coupon.name,
                                coupon.verification_code,
                                coupon.qr_token,
                                coupon.food_preference,
                                1 if coupon.include_qr else 0,
                                coupon.status,
                                coupon.event_name,
                                coupon.encrypted_data,
                                json.dumps(coupon.extra, ensure_ascii=False),
                                coupon.meal_key,
                                coupon.meal_label,
                                coupon.meal_order,
                                coupon.created_at,
                            ),
                        )
                        issued.append(coupon)
                        existing.add((email, session.key))
                    except Exception as exc:  # reported per pair, not raised
                        logger.exception(
                            "Could not issue %s coupon for %s",
                            session.key or "event", email,
                        )
                        errors.append({
                            "email": email, "meal": session.key, "error": str(exc),
                        })

        return {
            "issued": issued,
            "issued_count": len(issued),
            "skipped": skipped,
            "skipped_count": len(skipped),
            "errors": errors,
            "error_count": len(errors),
            "sessions": [s.to_dict() for s in sessions],
        }

    def issue_one(self, recipient: Recipient, event_name: str = "") -> Optional[Coupon]:
        result = self.issue_batch([recipient], event_name)
        return result["issued"][0] if result["issued"] else None
