"""Read GLEIF JSON:API bodies. A field that is absent stays absent."""
from __future__ import annotations

import json

REGISTRATION_STATUSES = {
    "PENDING_VALIDATION",
    "ISSUED",
    "DUPLICATE",
    "LAPSED",
    "MERGED",
    "RETIRED",
    "ANNULLED",
    "CANCELLED",
    "TRANSFERRED",
    "PENDING_TRANSFER",
    "PENDING_ARCHIVAL",
}
ENTITY_STATUSES = {"ACTIVE", "INACTIVE", "NULL"}
EXCEPTION_REASONS = {
    "NO_LEI",
    "NATURAL_PERSONS",
    "NON_CONSOLIDATING",
    "NO_KNOWN_PERSON",
    "NON_PUBLIC",
    "BINDING_LEGAL_COMMITMENTS",
    "LEGAL_OBSTACLES",
    "DISCLOSURE_DETRIMENTAL",
    "DETRIMENT_NOT_EXCLUDED",
    "CONSENT_NOT_OBTAINED",
}
DEPRECATED_REASONS = {
    "BINDING_LEGAL_COMMITMENTS",
    "LEGAL_OBSTACLES",
    "DISCLOSURE_DETRIMENTAL",
    "DETRIMENT_NOT_EXCLUDED",
    "CONSENT_NOT_OBTAINED",
}
REASON_GLOSS = {
    "NO_LEI": "The reporting exception says the parent has no LEI.",
    "NATURAL_PERSONS": "The reporting exception says the parent is a natural person.",
    "NON_CONSOLIDATING": "The reporting exception says there is no consolidating parent.",
    "NO_KNOWN_PERSON": "The reporting exception says there is no known person.",
    "NON_PUBLIC": "The reporting exception says the parent is non-public.",
}


def loads(body: bytes) -> dict | None:
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def golden_copy(doc: dict) -> str | None:
    meta = doc.get("meta")
    if not isinstance(meta, dict):
        return None
    block = meta.get("goldenCopy")
    if not isinstance(block, dict):
        return None
    published = block.get("publishDate")
    if isinstance(published, str) and published:
        return published
    return None


def error_parts(doc: dict) -> tuple[str, str] | None:
    errors = doc.get("errors")
    if not isinstance(errors, list) or not errors or not isinstance(errors[0], dict):
        return None
    status = errors[0].get("status")
    detail = errors[0].get("detail")
    title = errors[0].get("title")
    status_text = status if isinstance(status, str) else ""
    detail_text = detail if isinstance(detail, str) else ""
    if not detail_text and isinstance(title, str):
        detail_text = title
    return status_text, detail_text


def is_related_miss(doc: dict) -> bool:
    parts = error_parts(doc)
    if parts is None:
        return False
    status, detail = parts
    return status == "404" and detail == "Related resource not found"


def is_record_miss(doc: dict) -> bool:
    parts = error_parts(doc)
    if parts is None:
        return False
    status, detail = parts
    return status == "404" and detail.startswith("Resource lei-records with id ") and detail.endswith(" does not exist.")


def caution_line(registration: object, entity: object) -> str:
    """One line. A status outside the published lists is quoted and left untranslated."""
    notes = []
    if not isinstance(registration, str) or registration not in REGISTRATION_STATUSES:
        shown = registration if isinstance(registration, str) and registration else "absent"
        notes.append(f"registration.status is {shown}, outside the published list")
    elif registration != "ISSUED":
        notes.append(f"registration.status is {registration}")
    if not isinstance(entity, str) or entity not in ENTITY_STATUSES:
        shown = entity if isinstance(entity, str) and entity else "absent"
        notes.append(f"entity.status is {shown}, outside the published list")
    elif entity != "ACTIVE":
        notes.append(f"entity.status is {entity}")
    if not notes:
        return ""
    return "Caution: " + " and ".join(notes) + "."


def lei_record(doc: dict) -> dict | None:
    data = doc.get("data")
    if not isinstance(data, dict) or data.get("type") != "lei-records":
        return None
    lei = data.get("id")
    attrs = data.get("attributes")
    if not isinstance(lei, str) or not isinstance(attrs, dict):
        return None
    entity = attrs.get("entity") if isinstance(attrs.get("entity"), dict) else {}
    legal = entity.get("legalName") if isinstance(entity.get("legalName"), dict) else {}
    name = legal.get("name") if isinstance(legal.get("name"), str) else None
    registration = attrs.get("registration") if isinstance(attrs.get("registration"), dict) else {}
    reg_status = registration.get("status") if isinstance(registration.get("status"), str) else None
    ent_status = entity.get("status") if isinstance(entity.get("status"), str) else None
    return {
        "lei": lei,
        "legal_name": name,
        "registration_status": reg_status,
        "entity_status": ent_status,
        "golden_copy": golden_copy(doc),
        "caution": caution_line(reg_status, ent_status),
    }


def exception_record(doc: dict) -> dict | None:
    data = doc.get("data")
    if not isinstance(data, dict) or data.get("type") != "reporting-exceptions":
        return None
    attrs = data.get("attributes")
    if not isinstance(attrs, dict):
        return None
    reason = attrs.get("reason") if isinstance(attrs.get("reason"), str) else None
    category = attrs.get("category") if isinstance(attrs.get("category"), str) else None
    lei = attrs.get("lei") if isinstance(attrs.get("lei"), str) else None
    if reason in REASON_GLOSS:
        gloss = REASON_GLOSS[reason]
    elif reason in DEPRECATED_REASONS:
        gloss = "The reporting exception uses a deprecated reason code. The code is quoted as published."
    elif reason in EXCEPTION_REASONS:
        gloss = "The reporting exception reason is quoted as published."
    else:
        gloss = "The reason code is outside the published exception list. No parent was inferred."
    return {
        "lei": lei,
        "reason": reason,
        "category": category,
        "gloss": gloss,
        "golden_copy": golden_copy(doc),
    }


def collection(doc: dict) -> dict | None:
    data = doc.get("data")
    if not isinstance(data, list):
        return None
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    page = meta.get("pagination") if isinstance(meta.get("pagination"), dict) else {}
    links = doc.get("links") if isinstance(doc.get("links"), dict) else {}
    total = page.get("total") if isinstance(page.get("total"), int) and not isinstance(page.get("total"), bool) else None
    current = page.get("currentPage") if isinstance(page.get("currentPage"), int) else None
    last = page.get("lastPage") if isinstance(page.get("lastPage"), int) else None
    has_next = bool(links.get("next"))
    rows = [row for row in data if isinstance(row, dict)]
    if len(rows) != len(data):
        return None
    complete = not has_next and total is not None and total == len(rows)
    past_end = current is not None and last is not None and current > last
    return {
        "rows": rows,
        "total": total,
        "current_page": current,
        "last_page": last,
        "has_next": has_next,
        "complete": complete,
        "past_end": past_end,
        "golden_copy": golden_copy(doc),
    }


def record_row(row: dict) -> dict | None:
    if row.get("type") != "lei-records":
        return None
    return lei_record({"data": row, "meta": {}})


def fuzzy_values(doc: dict) -> list[str] | None:
    data = doc.get("data")
    if not isinstance(data, list):
        return None
    values = []
    for row in data:
        if not isinstance(row, dict) or row.get("type") != "fuzzycompletions":
            return None
        attrs = row.get("attributes")
        if not isinstance(attrs, dict) or not isinstance(attrs.get("value"), str):
            return None
        values.append(attrs["value"])
    return values
