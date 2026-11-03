"""LEI tools. A name search never requests a parent."""
from __future__ import annotations

import json

if __package__:
    from . import errors, parse
    from .client import UrllibTransport
else:
    import errors
    import parse
    from client import UrllibTransport

_TRANSPORT = None


def default_transport():
    global _TRANSPORT
    if _TRANSPORT is None:
        _TRANSPORT = UrllibTransport()
    return _TRANSPORT


def fail(template: dict, **extra) -> dict:
    out = dict(template)
    out.update(extra)
    return out


def dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _mod97(value: str) -> int:
    acc = 0
    for char in value:
        if "A" <= char <= "Z":
            piece = str(ord(char) - 55)
        elif "0" <= char <= "9":
            piece = char
        else:
            return -1
        for digit in piece:
            acc = (acc * 10 + int(digit)) % 97
    return acc


def _az09(value: str) -> bool:
    # str.isupper() is false for a digit-only string, so it cannot decide an LEI.
    return all(("A" <= char <= "Z") or ("0" <= char <= "9") for char in value)


def lei_ok(value: str) -> bool:
    if len(value) != 20 or not _az09(value):
        return False
    return _mod97(value) == 1


def isin_ok(value: str) -> bool:
    """ISO 6166 check digit. Letters expand to numbers, then the Luhn sum is used."""
    if len(value) != 12 or not _az09(value):
        return False
    if not ("A" <= value[0] <= "Z" and "A" <= value[1] <= "Z"):
        return False
    digits = []
    for char in value:
        if "A" <= char <= "Z":
            digits.append(str(ord(char) - 55))
        elif "0" <= char <= "9":
            digits.append(char)
        else:
            return False
    expanded = "".join(digits)
    total = 0
    for index, char in enumerate(reversed(expanded)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def fold_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _plain(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    text = " ".join(value.split())
    if not text or len(text) > limit:
        return None
    return text


def _page(value: object) -> int | str | None:
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int):
        return "bad"
    if value < 1 or value > 3:
        return "range"
    return value


def _only(args: dict, allowed: set[str]) -> bool:
    return set(args) <= allowed


def _http_fail(result) -> dict | None:
    if result.kind == "redirect":
        return fail(errors.REDIRECTED)
    if result.kind == "truncated":
        return fail(errors.TRUNCATED)
    if result.kind == "timeout":
        return fail(errors.UPSTREAM_DOWN, error="The API timed out before the body was read.")
    if result.kind == "connection":
        return fail(errors.UPSTREAM_DOWN, error="The API connection failed before the body was read.")
    if result.kind != "ok" and result.status == 429:
        return fail(errors.RATE_LIMITED)
    if result.kind != "ok" and result.status == 404:
        return None
    if result.kind != "ok":
        return fail(errors.UPSTREAM_ERROR, error=f"The API returned {result.status}.")
    return None


def _doc(result) -> tuple[dict | None, dict | None]:
    problem = _http_fail(result)
    if problem is not None:
        return None, problem
    if result.status == 404:
        doc = parse.loads(result.body)
        if doc is None:
            return None, fail(errors.BAD_BODY)
        return doc, None
    doc = parse.loads(result.body)
    if doc is None:
        return None, fail(errors.BAD_BODY)
    return doc, None


def _get(transport, segments, query) -> tuple[dict | None, dict | None, object]:
    client = default_transport() if transport is None else transport
    result = client.get(segments, query)
    doc, problem = _doc(result)
    return doc, problem, result


def _record_payload(row: dict, *, parents: str) -> dict:
    return {
        "ok": True,
        "lei": row["lei"],
        "legal_name": row["legal_name"],
        "registration_status": row["registration_status"],
        "entity_status": row["entity_status"],
        "golden_copy": row["golden_copy"],
        "caution": row["caution"],
        "parents": parents,
        "next_step": "Call lei_parents with this LEI when you want the official parent records.",
    }


def lookup_lei(lei: str, transport) -> dict:
    code = lei.strip().upper() if isinstance(lei, str) else ""
    if not lei_ok(code):
        return fail(errors.LEI_INVALID)
    doc, problem, _result = _get(transport, ("lei-records", code), {})
    if problem:
        return problem
    if doc is not None and parse.is_record_miss(doc):
        return fail(errors.LEI_NOT_FOUND)
    if doc is None:
        return fail(errors.BAD_BODY)
    row = parse.lei_record(doc)
    if row is None or row["lei"] != code:
        return fail(errors.UNKNOWN_SHAPE)
    return _record_payload(row, parents="not_requested")


def lookup_name(legal_name: str, page: int, transport) -> dict:
    text = _plain(legal_name, 200)
    if text is None:
        return fail(errors.NAME_INVALID)
    query = {
        "filter[entity.legalName]": text,
        "page[size]": "5",
        "page[number]": str(page),
    }
    doc, problem, _result = _get(transport, ("lei-records",), query)
    if problem:
        return problem
    if doc is None:
        return fail(errors.BAD_BODY)
    page_body = parse.collection(doc)
    if page_body is None:
        return fail(errors.UNKNOWN_SHAPE)
    candidates = []
    wanted = fold_name(text)
    differs = False
    for raw in page_body["rows"]:
        row = parse.record_row(raw)
        if row is None:
            return fail(errors.UNKNOWN_SHAPE)
        name_differs = fold_name(row["legal_name"] or "") != wanted
        differs = differs or name_differs
        candidates.append({
            "lei": row["lei"],
            "legal_name": row["legal_name"],
            "name_differs": name_differs,
            "registration_status": row["registration_status"],
            "entity_status": row["entity_status"],
            "caution": row["caution"],
        })
    if page_body["past_end"]:
        step = "This page is past the reported last page. Earlier pages were not read in this call."
    elif page_body["complete"] and not candidates:
        step = "The legal name filter returned no LEI record. Parents were not requested."
    elif not page_body["complete"] and differs:
        step = "This page is incomplete, and a returned legal name differs from the query. Pick a LEI from the rows that were read, then call lei_lookup. Parents were not requested."
    elif not page_body["complete"]:
        step = "This page is incomplete. Pick a LEI from the rows that were read, then call lei_lookup. Parents were not requested."
    elif differs:
        step = "A returned legal name differs from the query. Pick a LEI and call lei_lookup. Parents were not requested."
    else:
        step = "Call lei_parents with the LEI you choose. Parents were not requested."
    return {
        "ok": True,
        "query": text,
        "complete": page_body["complete"],
        "total": page_body["total"],
        "golden_copy": page_body["golden_copy"],
        "candidates": candidates,
        "parents": "not_requested",
        "next_step": step,
    }


def _side_from_parent(doc: dict, child: str) -> dict | None:
    row = parse.lei_record(doc)
    if row is None or row["lei"] == child:
        return None
    return {
        "kind": "official_parent",
        "parent_lei": row["lei"],
        "legal_name": row["legal_name"],
        "registration_status": row["registration_status"],
        "entity_status": row["entity_status"],
        "golden_copy": row["golden_copy"],
        "caution": row["caution"],
    }


def _side_from_exception(doc: dict, child: str) -> dict | None:
    row = parse.exception_record(doc)
    if row is None or row["lei"] not in {None, child}:
        return None
    return {
        "kind": "reporting_exception",
        "reason": row["reason"],
        "category": row["category"],
        "gloss": row["gloss"],
        "parent_lei": None,
        "golden_copy": row["golden_copy"],
    }


def _unknown_side(error_type: str, next_step: str | None = None) -> dict:
    side = {
        "ok": False,
        "kind": "unknown",
        "error_type": error_type,
        "parent_lei": None,
    }
    if next_step:
        side["next_step"] = next_step
    return side


def _one_side(transport, child: str, parent_segment: str, exception_segment: str) -> dict:
    doc, problem, result = _get(transport, ("lei-records", child, parent_segment), {})
    if problem:
        return _unknown_side(problem["error_type"], problem.get("next_step"))
    if result.status == 200 and doc is not None:
        side = _side_from_parent(doc, child)
        if side is None:
            return _unknown_side("unknown_shape")
        return side
    if doc is None or not parse.is_related_miss(doc):
        return _unknown_side("unknown_shape")
    exc_doc, exc_problem, exc_result = _get(
        transport, ("lei-records", child, exception_segment), {}
    )
    if exc_problem:
        return _unknown_side(exc_problem["error_type"], exc_problem.get("next_step"))
    if exc_result.status == 200 and exc_doc is not None:
        side = _side_from_exception(exc_doc, child)
        if side is None:
            return _unknown_side("unknown_shape")
        return side
    if exc_doc is not None and parse.is_related_miss(exc_doc):
        return {
            "kind": "no_official_record",
            "parent_lei": None,
            "next_step": "No official parent record and no reporting exception were in the response. The 404 was not retried.",
        }
    return _unknown_side("unknown_shape")


def parents(args: dict, transport) -> dict:
    if not isinstance(args, dict) or not _only(args, {"lei"}):
        return fail(errors.ARGS_INVALID)
    code = args.get("lei")
    code = code.strip().upper() if isinstance(code, str) else ""
    if not lei_ok(code):
        return fail(errors.LEI_INVALID)
    record = lookup_lei(code, transport)
    if not record.get("ok"):
        return record
    direct = _one_side(transport, code, "direct-parent", "direct-parent-reporting-exception")
    ultimate = _one_side(transport, code, "ultimate-parent", "ultimate-parent-reporting-exception")
    known = {"official_parent", "reporting_exception", "no_official_record"}
    parents_complete = direct.get("kind") in known and ultimate.get("kind") in known
    if not parents_complete:
        step = "One parent side was not read to the end. Do not treat that side as a miss."
    elif direct.get("kind") == "reporting_exception" or ultimate.get("kind") == "reporting_exception":
        step = "Quote the reporting exception reason. A parent LEI was not in that record."
    elif direct.get("kind") == "no_official_record" or ultimate.get("kind") == "no_official_record":
        step = "An explicit miss means both the parent record and the reporting exception were 404. Do not infer a parent."
    else:
        step = "Quote the parent LEI and legal name from the official record."
    return {
        "ok": True,
        "lei": record["lei"],
        "legal_name": record["legal_name"],
        "registration_status": record["registration_status"],
        "entity_status": record["entity_status"],
        "golden_copy": record["golden_copy"],
        "caution": record["caution"],
        "direct": direct,
        "ultimate": ultimate,
        "parents_complete": parents_complete,
        "next_step": step,
    }


def _child_page(args: dict, transport, segment: str, empty_step: str) -> dict:
    if not isinstance(args, dict) or not _only(args, {"lei", "page"}):
        return fail(errors.ARGS_INVALID)
    page = _page(args.get("page"))
    if page == "bad":
        return fail(errors.ARGS_INVALID)
    if page == "range":
        return fail(errors.PAGE_REFUSED)
    code = args.get("lei")
    code = code.strip().upper() if isinstance(code, str) else ""
    if not lei_ok(code):
        return fail(errors.LEI_INVALID)
    query = {"page[size]": "5", "page[number]": str(page)}
    doc, problem, result = _get(transport, ("lei-records", code, segment), query)
    if problem:
        return problem
    if result.status == 404 and doc is not None and parse.is_record_miss(doc):
        return fail(errors.LEI_NOT_FOUND)
    if result.status == 404:
        return fail(errors.UNKNOWN_SHAPE, error="The children resource was not a complete empty page.")
    if doc is None:
        return fail(errors.BAD_BODY)
    page_body = parse.collection(doc)
    if page_body is None:
        return fail(errors.UNKNOWN_SHAPE)
    children = []
    for raw in page_body["rows"]:
        row = parse.record_row(raw)
        if row is None:
            return fail(errors.UNKNOWN_SHAPE)
        children.append({
            "lei": row["lei"],
            "legal_name": row["legal_name"],
            "registration_status": row["registration_status"],
            "entity_status": row["entity_status"],
            "caution": row["caution"],
        })
    if page_body["past_end"]:
        step = "This page is past the reported last page. Earlier pages were not read in this call."
        complete = False
    elif page_body["complete"] and not children:
        step = empty_step
        complete = True
    elif page_body["complete"]:
        step = "This page matches the reported total."
        complete = True
    else:
        step = "Another page was not read. Do not treat this page as the full list."
        complete = False
    return {
        "ok": True,
        "lei": code,
        "complete": complete,
        "total": page_body["total"],
        "golden_copy": page_body["golden_copy"],
        "children": children,
        "next_step": step,
    }


def children(args: dict, transport) -> dict:
    return _child_page(
        args,
        transport,
        "direct-children",
        "This response lists no direct child record.",
    )


def search(args: dict, transport) -> dict:
    if not isinstance(args, dict) or not _only(args, {"q"}):
        return fail(errors.ARGS_INVALID)
    text = _plain(args.get("q"), 80)
    if text is None:
        return fail(errors.QUERY_INVALID)
    doc, problem, _result = _get(
        transport,
        ("fuzzycompletions",),
        {"field": "entity.legalName", "q": text},
    )
    if problem:
        return problem
    if doc is None:
        return fail(errors.BAD_BODY)
    values = parse.fuzzy_values(doc)
    if values is None:
        return fail(errors.UNKNOWN_SHAPE)
    if values:
        step = "These are name candidates from the response. Call lei_lookup with a legal name you choose. Parents were not requested."
    else:
        step = "The fuzzy search returned no legal-name candidate. Parents were not requested."
    return {
        "ok": True,
        "query": text,
        "candidates": values,
        "parents": "not_requested",
        "golden_copy": parse.golden_copy(doc),
        "next_step": step,
    }


def isin_map(args: dict, transport) -> dict:
    if not isinstance(args, dict) or not _only(args, {"isin", "lei", "page"}):
        return fail(errors.ARGS_INVALID)
    has_isin = "isin" in args
    has_lei = "lei" in args
    if has_isin == has_lei:
        return fail(errors.ARGS_INVALID)
    page = _page(args.get("page"))
    if page == "bad":
        return fail(errors.ARGS_INVALID)
    if page == "range":
        return fail(errors.PAGE_REFUSED)
    if has_lei:
        return _child_page_isins(args, page, transport)
    text = args.get("isin")
    code = text.strip().upper() if isinstance(text, str) else ""
    if not isin_ok(code):
        return fail(errors.ISIN_INVALID)
    query = {"filter[isin]": code, "page[size]": "5", "page[number]": str(page)}
    doc, problem, _result = _get(transport, ("lei-records",), query)
    if problem:
        return problem
    if doc is None:
        return fail(errors.BAD_BODY)
    page_body = parse.collection(doc)
    if page_body is None:
        return fail(errors.UNKNOWN_SHAPE)
    rows = []
    for raw in page_body["rows"]:
        row = parse.record_row(raw)
        if row is None:
            return fail(errors.UNKNOWN_SHAPE)
        rows.append({
            "lei": row["lei"],
            "legal_name": row["legal_name"],
            "registration_status": row["registration_status"],
            "entity_status": row["entity_status"],
            "caution": row["caution"],
        })
    if page_body["past_end"]:
        step = "This page is past the reported last page. Parents were not requested."
        complete = False
    elif page_body["complete"] and not rows:
        step = "The ISIN filter returned no LEI record. Parents were not requested."
        complete = True
    elif not page_body["complete"]:
        step = "This page is incomplete. Parents were not requested."
        complete = False
    else:
        step = "The ISIN filter returned these LEI records. Parents were not requested."
        complete = True
    return {
        "ok": True,
        "isin": code,
        "complete": complete,
        "total": page_body["total"],
        "golden_copy": page_body["golden_copy"],
        "records": rows,
        "parents": "not_requested",
        "next_step": step,
    }


def _child_page_isins(args: dict, page: int, transport) -> dict:
    code = args.get("lei")
    code = code.strip().upper() if isinstance(code, str) else ""
    if not lei_ok(code):
        return fail(errors.LEI_INVALID)
    doc, problem, result = _get(
        transport,
        ("lei-records", code, "isins"),
        {"page[size]": "5", "page[number]": str(page)},
    )
    if problem:
        return problem
    if result.status == 404 and doc is not None and parse.is_record_miss(doc):
        return fail(errors.LEI_NOT_FOUND)
    if result.status == 404:
        return fail(errors.UNKNOWN_SHAPE)
    if doc is None:
        return fail(errors.BAD_BODY)
    page_body = parse.collection(doc)
    if page_body is None:
        return fail(errors.UNKNOWN_SHAPE)
    isins = []
    for raw in page_body["rows"]:
        attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
        isin = attrs.get("isin")
        if not isinstance(isin, str):
            return fail(errors.UNKNOWN_SHAPE)
        isins.append(isin)
    if page_body["past_end"]:
        step = "This page is past the reported last page. Earlier pages were not read in this call."
        complete = False
    elif page_body["complete"] and not isins:
        step = "This response lists no ISIN."
        complete = True
    elif page_body["complete"]:
        step = "This page matches the reported total."
        complete = True
    else:
        step = "Another page was not read. Do not treat this page as the full ISIN list."
        complete = False
    return {
        "ok": True,
        "lei": code,
        "complete": complete,
        "total": page_body["total"],
        "golden_copy": page_body["golden_copy"],
        "isins": isins,
        "parents": "not_requested",
        "next_step": step,
    }


def lookup(args: dict, transport) -> dict:
    if not isinstance(args, dict) or not _only(args, {"lei", "legal_name", "page"}):
        return fail(errors.ARGS_INVALID)
    has_lei = "lei" in args
    has_name = "legal_name" in args
    if has_lei == has_name:
        return fail(errors.ARGS_INVALID)
    if has_lei and "page" in args:
        return fail(errors.ARGS_INVALID)
    if has_lei:
        return lookup_lei(args.get("lei"), transport)
    page = _page(args.get("page"))
    if page == "bad":
        return fail(errors.ARGS_INVALID)
    if page == "range":
        return fail(errors.PAGE_REFUSED)
    return lookup_name(args.get("legal_name"), page, transport)


TOOLS = {
    "lei_lookup": lookup,
    "lei_parents": parents,
    "lei_children": children,
    "lei_search": search,
    "lei_isin": isin_map,
}


def invoke(name: str, args: dict, transport=None) -> dict:
    fn = TOOLS.get(name)
    if fn is None:
        return fail(errors.UNKNOWN_TOOL)
    if not isinstance(args, dict):
        return fail(errors.ARGS_INVALID)
    return fn(args, transport or default_transport())
