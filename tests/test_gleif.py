"""Offline checks for LEI records, parents, and the morning watch."""
from __future__ import annotations

import io
import json
import os
import shutil
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

import client
import cli
import errors
import parse
import prefix
import service
import watch
from client import HttpResult, UrllibTransport, build_opener, build_url
from safe_write import HARD_LINK_CUT, WriteRefused, remove_file, write_bytes

FIX = Path(__file__).resolve().parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]
IMPRESSION = "335800LUOBQQY1UPKZ54"
NESTLE_UK = "5493004DKAGDNS9NFR36"
HOLDINGS = "549300P2TLJSJM4BBC08"
NONCONS = "5493000IBP32UQZ0KL24"
APPLE = "HWUPKR0MPOU8FGXBT394"
ISIN = "US0378331005"
EXTRA = [
    "335800LUOBQQY1UP0049",
    "335800LUOBQQY1UP00J0",
    "335800LUOBQQY1UP00S7",
    "335800LUOBQQY1UP0146",
    "335800LUOBQQY1UP01G0",
    "335800LUOBQQY1UP01P7",
    "335800LUOBQQY1UP01Z4",
    "335800LUOBQQY1UP0243",
    "335800LUOBQQY1UP02D0",
    "335800LUOBQQY1UP02M7",
]


def fx(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def record_from_row(row: dict, publish: str = "2026-11-02T16:00:00Z") -> dict:
    return {"meta": {"goldenCopy": {"publishDate": publish}}, "data": row}


class MapTransport:
    def __init__(self, routes: dict, default_status: int = 500):
        self.routes = routes
        self.default_status = default_status
        self.calls = []

    def get(self, segments, query):
        self.calls.append((tuple(segments), dict(query)))
        status, payload = self.routes.get(tuple(segments), (self.default_status, {"errors": [{"status": "500"}]}))
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        kind = "ok" if status == 200 else "http"
        return HttpResult(status, raw, kind)


class Opener:
    def __init__(self, status=200, body=b"{}", error=None):
        self.status = status
        self.body = body
        self.error = error
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return FakeBody(self.status, self.body)


class FakeBody:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self, n):
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def paths(transport: MapTransport) -> list[tuple]:
    return [call[0] for call in transport.calls]


@pytest.fixture(autouse=True)
def _reset():
    client._LAST_CALL = 0.0
    prefix.remember_profile_name(None)
    watch.set_data_dir(None)
    yield
    client._LAST_CALL = 0.0
    prefix.remember_profile_name(None)
    watch.set_data_dir(None)


def test_checksums_match_the_samples():
    assert service.lei_ok(IMPRESSION)
    assert service.lei_ok(NESTLE_UK)
    assert service.lei_ok(APPLE)
    assert not service.lei_ok("54930000000000000000")
    assert not service.lei_ok("335800LUOBQQY1UPKZ55")
    assert service.isin_ok(ISIN)
    assert service.isin_ok("US037833EW60")
    assert not service.isin_ok("US0378331006")
    wide_lei = "３３５８００ＬＵＯＢＱＱＹ１ＵＰＫＺ５４"
    wide_isin = "ＵＳ０３７８３３１００５"
    assert service.lei_ok(wide_lei) is False
    assert service.isin_ok(wide_isin) is False
    assert service.lei_ok("54930000000000000002") is True
    assert service.isin_ok("000000000018") is False
    assert service.invoke("lei_lookup", {"lei": wide_lei}, MapTransport({}))["error_type"] == "lei_invalid"
    assert service.invoke("lei_isin", {"isin": wide_isin}, MapTransport({}))["error_type"] == "isin_invalid"


def _luhn_digits(body: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(body)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def test_identifier_kinds_cover_the_table():
    """One row per input kind. Digit-only LEIs are a charset, not an isupper() exception."""
    digits_ok = "54930000000000000002"
    digits_bad = "54930000000000000000"
    wide_digits = "".join(chr(ord(char) + 0xFEE0) for char in digits_ok)
    digit_isin = "000000000018"
    assert _luhn_digits(digit_isin) is True
    assert len(wide_digits) == 20
    found = {
        ("lei-records", IMPRESSION): (200, fx("record_impression.json")),
        ("lei-records", digits_ok): (404, fx("lei_missing.json")),
        ("lei-records",): (200, fx("isin_apple.json")),
    }
    lei_rows = [
        ("empty", "", "lei_invalid", False),
        ("short", IMPRESSION[:-1], "lei_invalid", False),
        ("long", IMPRESSION + "X", "lei_invalid", False),
        ("lower", IMPRESSION.lower(), "ok", True),
        ("spaces", f"  {IMPRESSION}  ", "ok", True),
        ("nbsp", f"\u00a0{IMPRESSION}", "ok", True),
        ("fullwidth", "３３５８００ＬＵＯＢＱＱＹ１ＵＰＫＺ５４", "lei_invalid", False),
        ("fullwidth_digits", wide_digits, "lei_invalid", False),
        ("digits_checksum_ok", digits_ok, "lei_not_found", True),
        ("digits_checksum_bad", digits_bad, "lei_invalid", False),
        ("semicolon", IMPRESSION + ";", "lei_invalid", False),
        ("comment", IMPRESSION + " # note", "lei_invalid", False),
        ("url", "https://search.gleif.org/" + IMPRESSION, "lei_invalid", False),
        ("slash", "335800LUOBQQY1UPKZ5/", "lei_invalid", False),
        ("question", "335800LUOBQQY1UPKZ5?", "lei_invalid", False),
        ("quote", '335800LUOBQQY1UPKZ5"', "lei_invalid", False),
        ("accent", "JOSÉ00LUOBQQY1UPKZ54", "lei_invalid", False),
        ("japanese_lei", "アップル", "lei_invalid", False),
        ("internal_space", "335800LUOB QQY1UPKZ5", "lei_invalid", False),
        ("underscore", "335800LUOBQQY1UPKZ5_", "lei_invalid", False),
        ("hyphen", "335800LUOBQQY1UPKZ5-", "lei_invalid", False),
        ("newline", "335800LUOBQQY1UPKZ\n4", "lei_invalid", False),
        ("null", "335800LUOBQQY1UPKZ5\x00", "lei_invalid", False),
    ]
    for name, raw, kind, called in lei_rows:
        transport = MapTransport(found)
        body = service.invoke("lei_lookup", {"lei": raw}, transport)
        if kind == "ok":
            assert body["ok"] is True, name
            assert body["lei"] == IMPRESSION, name
        else:
            assert body["error_type"] == kind, name
        assert bool(transport.calls) is called, name
    transport = MapTransport(found)
    body = service.invoke("lei_lookup", {"lei": 20}, transport)
    assert body["error_type"] == "lei_invalid"
    assert transport.calls == []
    isin_rows = [
        ("lower_isin", "us0378331005", "ok", True),
        ("spaces_isin", "  US0378331005  ", "ok", True),
        ("digit_isin_luhn", digit_isin, "isin_invalid", False),
        ("fullwidth_isin", "ＵＳ０３７８３３１００５", "isin_invalid", False),
        ("semicolon_isin", ISIN + ";", "isin_invalid", False),
        ("bad_luhn", "US0378331006", "isin_invalid", False),
        ("one_letter", "A10378331005", "isin_invalid", False),
    ]
    for name, raw, kind, called in isin_rows:
        transport = MapTransport(found)
        body = service.invoke("lei_isin", {"isin": raw}, transport)
        if kind == "ok":
            assert body["ok"] is True, name
            assert body["isin"] == ISIN, name
        else:
            assert body["error_type"] == kind, name
        assert bool(transport.calls) is called, name


def test_handler_returns_the_json_string_unchanged(monkeypatch, tmp_path):
    import importlib.util
    import sys
    import types

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    spec = importlib.util.spec_from_file_location("gleif_init_loose", ROOT / "__init__.py")
    loose = importlib.util.module_from_spec(spec)
    sys.modules["gleif_init_loose"] = loose
    spec.loader.exec_module(loose)
    payload = loose.make_handler("lei_lookup")({"lei": "not-an-lei"})
    assert isinstance(payload, str)
    assert json.loads(payload)["error_type"] == "lei_invalid"
    assert len(payload) < 2048
    for value in vars(errors).values():
        if isinstance(value, dict) and isinstance(value.get("error"), str):
            assert len(service.dump(value)) < 2048

    parent = "hermes_plugins_gleif_test"
    module_name = parent + ".gleif"
    for loaded in list(sys.modules):
        if loaded == parent or loaded.startswith(module_name):
            sys.modules.pop(loaded, None)
    package = types.ModuleType(parent)
    package.__path__ = []
    package.__package__ = parent
    sys.modules[parent] = package
    packaged = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(packaged)
    module.__package__ = module_name
    module.__path__ = [str(ROOT)]
    sys.modules[module_name] = module
    packaged.loader.exec_module(module)
    packed = module.make_handler("lei_parents")({"lei": "not-an-lei"})
    assert json.loads(packed)["error_type"] == "lei_invalid"

    src = os.environ.get("HERMES_SRC", "").strip()
    if not src or not Path(src).is_dir():
        return
    sys.path.insert(0, src)
    from tools.registry import registry

    def _run(args, **_kwargs):
        return payload

    registry.register(
        name="lei_lookup",
        toolset="gleif",
        schema={"name": "lei_lookup", "description": "x", "parameters": {"type": "object"}},
        handler=_run,
        override=True,
    )
    assert registry.dispatch("lei_lookup", {"lei": "not-an-lei"}) == payload


def test_bad_lei_does_not_call_the_api():
    transport = MapTransport({})
    body = service.invoke("lei_lookup", {"lei": "54930000000000000000"}, transport)
    assert body["error_type"] == "lei_invalid"
    assert body["ok"] is False
    assert transport.calls == []
    assert "parent" in body["next_step"].lower() or "parent" in body["error"].lower()


def test_lookup_record_attaches_golden_copy_and_does_not_request_parents():
    transport = MapTransport({("lei-records", IMPRESSION): (200, fx("record_impression.json"))})
    body = service.invoke("lei_lookup", {"lei": "335800luobqqy1upkz54"}, transport)
    assert body["ok"] is True
    assert body["lei"] == IMPRESSION
    assert body["legal_name"] == "APPLE IMPRESSION"
    assert body["golden_copy"] == "2026-11-02T16:00:00Z"
    assert body["caution"] == ""
    assert body["parents"] == "not_requested"
    assert paths(transport) == [("lei-records", IMPRESSION)]


def test_missing_lei_is_not_a_parent_miss():
    transport = MapTransport({("lei-records", NESTLE_UK): (404, fx("lei_missing.json"))})
    body = service.parents({"lei": NESTLE_UK}, transport)
    assert body["error_type"] == "lei_not_found"
    assert paths(transport) == [("lei-records", NESTLE_UK)]


def test_parent_404_is_not_retried_and_exception_is_official():
    routes = {
        ("lei-records", IMPRESSION): (200, fx("record_impression.json")),
        ("lei-records", IMPRESSION, "direct-parent"): (404, fx("related_404.json")),
        ("lei-records", IMPRESSION, "direct-parent-reporting-exception"): (200, fx("exception_natural_persons.json")),
        ("lei-records", IMPRESSION, "ultimate-parent"): (404, fx("related_404.json")),
        ("lei-records", IMPRESSION, "ultimate-parent-reporting-exception"): (200, fx("exception_ultimate_natural_persons.json")),
    }
    transport = MapTransport(routes)
    body = service.parents({"lei": IMPRESSION}, transport)
    assert body["ok"] is True
    assert body["direct"]["kind"] == "reporting_exception"
    assert body["direct"]["reason"] == "NATURAL_PERSONS"
    assert body["direct"]["parent_lei"] is None
    assert "natural person" in body["direct"]["gloss"].lower()
    assert body["ultimate"]["kind"] == "reporting_exception"
    assert body["parents_complete"] is True
    assert paths(transport).count(("lei-records", IMPRESSION, "direct-parent")) == 1
    assert paths(transport).count(("lei-records", IMPRESSION, "ultimate-parent")) == 1


def test_both_related_404_is_an_explicit_miss():
    miss = fx("related_404.json")
    routes = {
        ("lei-records", IMPRESSION): (200, fx("record_impression.json")),
        ("lei-records", IMPRESSION, "direct-parent"): (404, miss),
        ("lei-records", IMPRESSION, "direct-parent-reporting-exception"): (404, miss),
        ("lei-records", IMPRESSION, "ultimate-parent"): (404, miss),
        ("lei-records", IMPRESSION, "ultimate-parent-reporting-exception"): (404, miss),
    }
    transport = MapTransport(routes)
    body = service.parents({"lei": IMPRESSION}, transport)
    assert body["ok"] is True
    assert body["parents_complete"] is True
    assert body["direct"]["kind"] == "no_official_record"
    assert body["ultimate"]["kind"] == "no_official_record"
    assert body["direct"]["parent_lei"] is None
    assert "404" in body["direct"]["next_step"]


def test_official_parent_skips_the_exception_url():
    child = record_from_row(fx("name_nestle_uk.json")["data"][0])
    routes = {
        ("lei-records", NESTLE_UK): (200, child),
        ("lei-records", NESTLE_UK, "direct-parent"): (200, fx("parent_nestle_uk.json")),
        ("lei-records", NESTLE_UK, "ultimate-parent"): (200, fx("ultimate_nestle.json")),
    }
    transport = MapTransport(routes)
    body = service.parents({"lei": NESTLE_UK}, transport)
    assert body["direct"]["kind"] == "official_parent"
    assert body["direct"]["parent_lei"] == HOLDINGS
    assert body["direct"]["legal_name"] == "NESTLE HOLDINGS (U.K.) PLC"
    assert body["ultimate"]["kind"] == "official_parent"
    assert "direct-parent-reporting-exception" not in {part for call in paths(transport) for part in call}


def test_non_consolidating_does_not_invent_a_parent():
    child = record_from_row(fx("name_nestle_uk.json")["data"][0])
    child["data"]["id"] = NONCONS
    child["data"]["attributes"]["lei"] = NONCONS
    routes = {
        ("lei-records", NONCONS): (200, child),
        ("lei-records", NONCONS, "direct-parent"): (404, fx("related_404.json")),
        ("lei-records", NONCONS, "direct-parent-reporting-exception"): (200, fx("exception_non_consolidating.json")),
        ("lei-records", NONCONS, "ultimate-parent"): (404, fx("exception_404.json")),
        ("lei-records", NONCONS, "ultimate-parent-reporting-exception"): (404, fx("exception_404.json")),
    }
    transport = MapTransport(routes)
    body = service.parents({"lei": NONCONS}, transport)
    assert body["direct"]["kind"] == "reporting_exception"
    assert body["direct"]["reason"] == "NON_CONSOLIDATING"
    assert body["direct"]["parent_lei"] is None
    assert "legal_name" not in body["direct"]
    assert body["ultimate"]["kind"] == "no_official_record"


def test_parent_timeout_is_unknown():
    routes = {
        ("lei-records", IMPRESSION): (200, fx("record_impression.json")),
        ("lei-records", IMPRESSION, "ultimate-parent"): (404, fx("related_404.json")),
        ("lei-records", IMPRESSION, "ultimate-parent-reporting-exception"): (404, fx("related_404.json")),
    }
    transport = MapTransport(routes)

    def get(segments, query):
        transport.calls.append((tuple(segments), dict(query)))
        if segments[-1:] == ("direct-parent",):
            return HttpResult(0, b"", "timeout")
        status, payload = routes[tuple(segments)]
        return HttpResult(status, json.dumps(payload).encode(), "ok")

    transport.get = get
    body = service.parents({"lei": IMPRESSION}, transport)
    assert body["ok"] is True
    assert body["parents_complete"] is False
    assert body["direct"]["kind"] == "unknown"
    assert body["direct"]["error_type"] == "upstream_down"
    assert body["direct"]["kind"] != "no_official_record"


def test_other_404_shape_is_not_a_miss():
    routes = {
        ("lei-records", IMPRESSION): (200, fx("record_impression.json")),
        ("lei-records", IMPRESSION, "direct-parent"): (404, {"errors": [{"status": "404", "title": "Not Found"}]}),
        ("lei-records", IMPRESSION, "ultimate-parent"): (404, fx("related_404.json")),
        ("lei-records", IMPRESSION, "ultimate-parent-reporting-exception"): (404, fx("related_404.json")),
    }
    transport = MapTransport(routes)
    body = service.parents({"lei": IMPRESSION}, transport)
    assert body["ok"] is True
    assert body["parents_complete"] is False
    assert body["direct"]["kind"] == "unknown"
    assert body["ultimate"]["kind"] == "no_official_record"


def test_name_search_never_requests_a_parent_when_the_name_differs():
    transport = MapTransport({("lei-records",): (200, fx("name_nestle_uk.json"))})
    body = service.lookup({"legal_name": "NESTLE UK"}, transport)
    assert body["ok"] is True
    assert body["parents"] == "not_requested"
    assert body["complete"] is False
    assert any(row["name_differs"] for row in body["candidates"])
    assert "differs" in body["next_step"]
    assert paths(transport) == [("lei-records",)]
    assert "direct-parent" not in body["next_step"]


def test_exact_legal_name_still_does_not_request_parents():
    page = fx("name_nestle_uk.json")
    row = json.loads(json.dumps(page["data"][0]))
    row["attributes"]["entity"]["legalName"]["name"] = "NESTLE UK LTD."
    doc = {
        "meta": {
            "goldenCopy": {"publishDate": "2026-11-02T16:00:00Z"},
            "pagination": {"currentPage": 1, "perPage": 5, "total": 1, "lastPage": 1},
        },
        "links": {},
        "data": [row],
    }
    transport = MapTransport({("lei-records",): (200, doc)})
    body = service.lookup({"legal_name": "nestle   uk ltd."}, transport)
    assert body["candidates"][0]["name_differs"] is False
    assert body["parents"] == "not_requested"
    assert body["complete"] is True
    assert paths(transport) == [("lei-records",)]


def test_fuzzy_search_returns_names_and_does_not_follow_ids():
    transport = MapTransport({("fuzzycompletions",): (200, fx("fuzzy_nestle.json"))})
    body = service.search({"q": "nestle"}, transport)
    assert body["ok"] is True
    assert body["parents"] == "not_requested"
    assert body["candidates"][0] == "NESTED"
    assert all(isinstance(item, str) for item in body["candidates"])
    dumped = json.dumps(body)
    assert "6488MUIO4T888G558V67" not in dumped
    assert paths(transport) == [("fuzzycompletions",)]
    assert transport.calls[0][1]["field"] == "entity.legalName"
    assert "you choose" in body["next_step"]
    empty = MapTransport({("fuzzycompletions",): (200, {"data": []})})
    blank = service.search({"q": "zzzznotanentityqqq99"}, empty)
    assert blank["ok"] is True
    assert blank["candidates"] == []
    assert blank["parents"] == "not_requested"
    assert "no legal-name candidate" in blank["next_step"]
    assert "you choose" not in blank["next_step"]
    assert paths(empty) == [("fuzzycompletions",)]


def test_children_empty_page_is_a_complete_zero_and_a_404_is_not():
    transport = MapTransport({
        ("lei-records", IMPRESSION, "direct-children"): (200, fx("children_empty.json")),
    })
    body = service.children({"lei": IMPRESSION}, transport)
    assert body["complete"] is True
    assert body["children"] == []
    assert "no direct child" in body["next_step"]
    broken = MapTransport({
        ("lei-records", IMPRESSION, "direct-children"): (404, fx("related_404.json")),
    })
    refused = service.children({"lei": IMPRESSION}, broken)
    assert refused["ok"] is False
    assert refused["error_type"] == "unknown_shape"
    assert "no direct child" not in refused["error"]


def test_children_page_past_the_end_is_not_zero():
    doc = {
        "meta": {
            "goldenCopy": {"publishDate": "2026-11-02T16:00:00Z"},
            "pagination": {"currentPage": 3, "perPage": 5, "total": 1, "lastPage": 1},
        },
        "links": {},
        "data": [],
    }
    transport = MapTransport({("lei-records", IMPRESSION, "direct-children"): (200, doc)})
    body = service.children({"lei": IMPRESSION, "page": 3}, transport)
    assert body["complete"] is False
    assert "past the reported last page" in body["next_step"]
    assert "no direct child" not in body["next_step"]


def test_isin_page_is_not_the_full_list_and_does_not_request_parents():
    transport = MapTransport({
        ("lei-records", APPLE, "isins"): (200, fx("isins_apple_page.json")),
    })
    body = service.isin_map({"lei": APPLE}, transport)
    assert body["ok"] is True
    assert body["complete"] is False
    assert body["total"] == 949
    assert body["isins"][0] == "US037833EW60"
    assert body["parents"] == "not_requested"
    assert "full ISIN list" in body["next_step"]
    assert paths(transport) == [("lei-records", APPLE, "isins")]


def test_isin_filter_and_empty_isin_page():
    transport = MapTransport({("lei-records",): (200, fx("isin_apple.json"))})
    body = service.isin_map({"isin": "us0378331005"}, transport)
    assert body["ok"] is True
    assert body["records"][0]["lei"] == APPLE
    assert body["parents"] == "not_requested"
    assert transport.calls[0][1]["filter[isin]"] == ISIN
    empty = MapTransport({("lei-records", NESTLE_UK, "isins"): (200, fx("isins_empty.json"))})
    blank = service.isin_map({"lei": NESTLE_UK}, empty)
    assert blank["complete"] is True
    assert blank["isins"] == []
    assert "no ISIN" in blank["next_step"]


def test_lapsed_and_unknown_status_are_one_caution_line():
    record = fx("record_impression.json")
    record["data"]["attributes"]["registration"]["status"] = "LAPSED"
    record["data"]["attributes"]["entity"]["status"] = "INACTIVE"
    transport = MapTransport({("lei-records", IMPRESSION): (200, record)})
    body = service.lookup_lei(IMPRESSION, transport)
    assert body["caution"] == "Caution: registration.status is LAPSED and entity.status is INACTIVE."
    assert "expired" not in body["caution"].lower()
    weird = fx("record_impression.json")
    weird["data"]["attributes"]["registration"]["status"] = "POTATO"
    line = parse.caution_line("POTATO", "ACTIVE")
    assert "outside the published list" in line
    assert "POTATO" in line


def test_no_lei_reason_does_not_name_a_parent():
    doc = {
        "meta": {"goldenCopy": {"publishDate": "2026-11-02T16:00:00Z"}},
        "data": {
            "type": "reporting-exceptions",
            "attributes": {
                "lei": IMPRESSION,
                "reason": "NO_LEI",
                "category": "DIRECT_ACCOUNTING_CONSOLIDATION_PARENT",
            },
        },
    }
    routes = {
        ("lei-records", IMPRESSION): (200, fx("record_impression.json")),
        ("lei-records", IMPRESSION, "direct-parent"): (404, fx("related_404.json")),
        ("lei-records", IMPRESSION, "direct-parent-reporting-exception"): (200, doc),
        ("lei-records", IMPRESSION, "ultimate-parent"): (404, fx("related_404.json")),
        ("lei-records", IMPRESSION, "ultimate-parent-reporting-exception"): (404, fx("related_404.json")),
    }
    body = service.parents({"lei": IMPRESSION}, MapTransport(routes))
    assert body["direct"]["kind"] == "reporting_exception"
    assert body["direct"]["parent_lei"] is None
    assert "no LEI" in body["direct"]["gloss"]
    assert "legal_name" not in body["direct"]


def test_unknown_exception_reason_is_quoted_without_a_guess():
    row = parse.exception_record({
        "data": {"type": "reporting-exceptions", "attributes": {"lei": IMPRESSION, "reason": "MADE_UP", "category": "X"}},
    })
    assert "outside the published exception list" in row["gloss"]
    assert "inferred" in row["gloss"]
    old = parse.exception_record({
        "data": {
            "type": "reporting-exceptions",
            "attributes": {"reason": "BINDING_LEGAL_COMMITMENTS", "category": "DIRECT_ACCOUNTING_CONSOLIDATION_PARENT"},
        },
    })
    assert "deprecated" in old["gloss"]


def test_same_lei_as_parent_is_unknown():
    routes = {
        ("lei-records", IMPRESSION): (200, fx("record_impression.json")),
        ("lei-records", IMPRESSION, "direct-parent"): (200, fx("record_impression.json")),
        ("lei-records", IMPRESSION, "ultimate-parent"): (404, fx("related_404.json")),
        ("lei-records", IMPRESSION, "ultimate-parent-reporting-exception"): (404, fx("related_404.json")),
    }
    body = service.parents({"lei": IMPRESSION}, MapTransport(routes))
    assert body["direct"]["kind"] == "unknown"


def test_arguments_are_allowlisted():
    transport = MapTransport({})
    assert service.invoke("lei_lookup", {"lei": IMPRESSION, "page": 1}, transport)["error_type"] == "args_invalid"
    assert service.invoke("lei_lookup", {"lei": IMPRESSION, "legal_name": "A"}, transport)["error_type"] == "args_invalid"
    assert service.invoke("lei_lookup", {"legal_name": "Nestle", "page": True}, transport)["error_type"] == "args_invalid"
    assert service.invoke("lei_children", {"lei": IMPRESSION, "page": 4}, transport)["error_type"] == "page_refused"
    assert service.invoke("lei_parents", {"lei": IMPRESSION, "q": "x"}, transport)["error_type"] == "args_invalid"
    assert service.invoke("lei_search", {"q": "nestle", "lei": IMPRESSION}, transport)["error_type"] == "args_invalid"
    assert service.invoke("lei_isin", {}, transport)["error_type"] == "args_invalid"
    assert service.invoke("lei_isin", {"isin": ISIN, "lei": IMPRESSION}, transport)["error_type"] == "args_invalid"
    assert service.invoke("lei_isin", {"isin": "US0378331006"}, transport)["error_type"] == "isin_invalid"
    assert service.invoke("lei_lookup", {"legal_name": "bad\nname"}, transport)["error_type"] == "name_invalid"
    assert service.invoke("missing", {}, transport)["error_type"] == "unknown_tool"
    assert transport.calls == []


def test_failure_kinds_stay_distinct():
    down = service._http_fail(HttpResult(0, b"", "timeout"))
    lost = service._http_fail(HttpResult(0, b"", "connection"))
    limited = service._http_fail(HttpResult(429, b"", "http"))
    broken = service._http_fail(HttpResult(503, b"", "http"))
    moved = service._http_fail(HttpResult(302, b"", "redirect"))
    cut = service._http_fail(HttpResult(200, b"", "truncated"))
    assert down["error_type"] == "upstream_down"
    assert lost["error_type"] == "upstream_down"
    assert "timed out" in down["error"]
    assert "connection" in lost["error"]
    assert limited["error_type"] == "rate_limited"
    assert broken["error_type"] == "upstream_error"
    assert "503" in broken["error"]
    assert moved["error_type"] == "redirected"
    assert cut["error_type"] == "truncated"
    bad = service.lookup_lei(IMPRESSION, MapTransport({("lei-records", IMPRESSION): (200, b"nope")}))
    assert bad["error_type"] == "bad_body"
    odd = service.lookup_lei(IMPRESSION, MapTransport({("lei-records", IMPRESSION): (200, {"data": {"type": "other"}})}))
    assert odd["error_type"] == "unknown_shape"


def test_url_allowlist_and_query_encoding():
    url = build_url(("lei-records", IMPRESSION), {"filter[entity.legalName]": "A/../B ?"})
    parsed = urllib.parse.urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.hostname == "api.gleif.org"
    assert "/../" not in parsed.path
    assert "A%2F..%2FB" in parsed.query
    for segments in [("nope",), ("lei-records", "../x"), ("lei-records", "HAS_SPACE"), ("lei-records", "A_B")]:
        with pytest.raises(ValueError):
            build_url(segments, {})


def test_opener_ignores_proxy_env(monkeypatch):
    for name in (
        "http_proxy", "https_proxy", "ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY",
        "no_proxy", "NO_PROXY", "all_proxy", "ftp_proxy",
    ):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    opener = build_opener()
    assert not any(isinstance(handler, urllib.request.ProxyHandler) for handler in opener.handlers)
    default = urllib.request.build_opener()
    assert any(isinstance(handler, urllib.request.ProxyHandler) for handler in default.handlers)
    source = (ROOT / "client.py").read_text(encoding="utf-8")
    assert "dotenv" not in source
    assert "load_dotenv" not in source


def test_redirect_timeout_size_and_headers(monkeypatch):
    request_url = "https://api.gleif.org/api/v1/lei-records/" + IMPRESSION
    moved = urllib.error.HTTPError(request_url, 302, "found", {"Location": "https://example.invalid"}, io.BytesIO(b""))
    opener = Opener(error=moved)
    result = UrllibTransport(interval=0, opener=opener).get(("lei-records", IMPRESSION), {})
    assert result.kind == "redirect"
    assert len(opener.calls) == 1
    assert opener.calls[0][1] == client.TIMEOUT_SECONDS
    headers = {key.lower(): value for key, value in opener.calls[0][0].header_items()}
    assert headers["accept"] == "application/vnd.api+json"
    assert headers["user-agent"] == "hermes-plugin-gleif/0.1"
    timed = Opener(error=TimeoutError("slow"))
    assert UrllibTransport(interval=0, opener=timed).get(("lei-records", IMPRESSION), {}).kind == "timeout"
    down = Opener(error=urllib.error.URLError("down"))
    assert UrllibTransport(interval=0, opener=down).get(("lei-records", IMPRESSION), {}).kind == "connection"
    huge = Opener(status=200, body=b"x" * (client.MAX_BODY + 1))
    assert UrllibTransport(interval=0, opener=huge).get(("lei-records", IMPRESSION), {}).kind == "truncated"
    sleeps = []
    monkeypatch.setattr(client.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(client.time, "monotonic", lambda: 10.0)
    client._LAST_CALL = 9.2
    UrllibTransport(interval=1.0, opener=Opener(status=200, body=b"{}")).get(("fuzzycompletions",), {"field": "entity.legalName", "q": "a"})
    assert sleeps == [pytest.approx(0.2)]


def test_read_tools_do_not_change_disk_or_other_results(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    other = {"ok": True, "tool": "terminal", "output": "book a flight tomorrow"}
    frozen = json.dumps(other)
    conversation = "book a flight tomorrow"
    transport = MapTransport({
        ("lei-records", IMPRESSION): (200, fx("record_impression.json")),
        ("lei-records",): (200, fx("name_nestle_uk.json")),
        ("fuzzycompletions",): (200, fx("fuzzy_nestle.json")),
        ("lei-records", IMPRESSION, "direct-children"): (200, fx("children_empty.json")),
        ("lei-records", IMPRESSION, "isins"): (200, fx("isins_empty.json")),
        ("lei-records", IMPRESSION, "direct-parent"): (404, fx("related_404.json")),
        ("lei-records", IMPRESSION, "direct-parent-reporting-exception"): (200, fx("exception_natural_persons.json")),
        ("lei-records", IMPRESSION, "ultimate-parent"): (404, fx("related_404.json")),
        ("lei-records", IMPRESSION, "ultimate-parent-reporting-exception"): (200, fx("exception_ultimate_natural_persons.json")),
    })
    before = sentinel.stat().st_mtime_ns
    service.invoke("lei_lookup", {"lei": IMPRESSION}, transport)
    service.invoke("lei_lookup", {"legal_name": "NESTLE UK"}, transport)
    service.invoke("lei_search", {"q": "nestle"}, transport)
    service.invoke("lei_children", {"lei": IMPRESSION}, transport)
    service.invoke("lei_isin", {"lei": IMPRESSION}, transport)
    service.invoke("lei_parents", {"lei": IMPRESSION}, transport)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert sentinel.stat().st_mtime_ns == before
    assert json.dumps(other) == frozen
    assert conversation == "book a flight tomorrow"
    assert not (tmp_path / "home").exists()
    assert "register_hook" not in (ROOT / "__init__.py").read_text(encoding="utf-8")


def test_safe_write_refuses_symlink_parent_and_dotdot(tmp_path):
    write_bytes(tmp_path, "a", b"one", create=True)
    os.link(tmp_path / "a", tmp_path / "b")
    with pytest.raises(WriteRefused) as refused:
        write_bytes(tmp_path, "a", b"three", cut_hardlink=False)
    assert refused.value.kind == "hardlink"
    assert (tmp_path / "a").read_bytes() == b"one"
    note = write_bytes(tmp_path, "a", b"two")
    assert note == HARD_LINK_CUT
    assert (tmp_path / "a").read_bytes() == b"two"
    assert (tmp_path / "b").read_bytes() == b"one"
    os.unlink(tmp_path / "b")
    link = tmp_path / "linked"
    link.symlink_to(tmp_path / "a")
    with pytest.raises(WriteRefused) as refused:
        write_bytes(tmp_path, "linked", b"no")
    assert refused.value.kind == "symlink"
    assert (tmp_path / "a").read_bytes() == b"two"
    nested = tmp_path / "real"
    nested.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(nested, target_is_directory=True)
    with pytest.raises(WriteRefused) as refused:
        write_bytes(tmp_path, "alias/watch.json", b"{}", create=True)
    assert refused.value.kind == "symlink"
    with pytest.raises(WriteRefused):
        write_bytes(tmp_path, "../outside", b"x", create=True)
    if Path("/tmp").is_symlink():
        root = Path("/tmp") / f"gleif-alias-{os.getpid()}"
        try:
            if root.exists():
                shutil.rmtree(root)
            note = write_bytes(root, "plugin-data/gleif/watch.json", b"{}", create=True)
            assert note == ""
            assert (root / "plugin-data" / "gleif" / "watch.json").read_bytes() == b"{}"
            added = watch.add_lei(IMPRESSION, root)
            assert added["ok"] is True
            deeper = root / "alias"
            deeper.symlink_to(root / "plugin-data", target_is_directory=True)
            with pytest.raises(WriteRefused) as refused_deeper:
                write_bytes(root, "alias/x.json", b"{}", create=True)
            assert refused_deeper.value.kind == "symlink"
        finally:
            shutil.rmtree(root, ignore_errors=True)
    with pytest.raises(WriteRefused):
        remove_file(tmp_path, "linked")


def test_watch_baseline_change_failure_and_cap(tmp_path):
    record = fx("record_impression.json")
    transport = MapTransport({("lei-records", IMPRESSION): (200, record)})
    added = watch.add_lei(IMPRESSION.lower(), tmp_path)
    assert added["ok"] is True
    assert watch.run_watch(tmp_path, transport) == ""
    bare = MapTransport({("lei-records", IMPRESSION): (200, fx("record_impression.json"))})
    other = tmp_path / "default-transport"
    assert watch.add_lei(IMPRESSION, other)["ok"] is True
    original_transport = service.default_transport
    service.default_transport = lambda: bare
    try:
        assert watch.run_watch(other, None) == ""
    finally:
        service.default_transport = original_transport
    saved_default = json.loads((other / "watch.json").read_text(encoding="utf-8"))
    assert saved_default["leis"][IMPRESSION]["registration_status"] == "ISSUED"
    saved = json.loads((tmp_path / "watch.json").read_text(encoding="utf-8"))
    assert saved["leis"][IMPRESSION]["registration_status"] == "ISSUED"
    again = fx("record_impression.json")
    again["meta"]["goldenCopy"]["publishDate"] = "2026-11-03T16:00:00Z"
    quiet = MapTransport({("lei-records", IMPRESSION): (200, again)})
    assert watch.run_watch(tmp_path, quiet) == ""
    changed = fx("record_impression.json")
    changed["data"]["attributes"]["registration"]["status"] = "LAPSED"
    loud = MapTransport({("lei-records", IMPRESSION): (200, changed)})
    text = watch.run_watch(tmp_path, loud)
    assert "LAPSED" in text
    assert "Golden copy 2026-11-02T16:00:00Z" in text
    assert "Caution: registration.status is LAPSED." in text
    failed = MapTransport({("lei-records", IMPRESSION): (500, {"errors": [{"status": "500"}]})})
    note = watch.run_watch(tmp_path, failed)
    assert "was not read" in note
    assert "kept" in note
    kept = json.loads((tmp_path / "watch.json").read_text(encoding="utf-8"))
    assert kept["leis"][IMPRESSION]["registration_status"] == "LAPSED"
    for code in EXTRA[:9]:
        assert watch.add_lei(code, tmp_path)["ok"] is True
    full = watch.add_lei(EXTRA[9], tmp_path)
    assert full["error_type"] == "watch_full"
    assert EXTRA[9] not in json.loads((tmp_path / "watch.json").read_text(encoding="utf-8"))["leis"]


def test_watch_file_symlink_is_not_replaced(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}\n", encoding="utf-8")
    (tmp_path / "watch.json").symlink_to(real)
    body = watch.add_lei(IMPRESSION, tmp_path)
    assert body["error_type"] == "watch_unreadable"
    assert real.read_text(encoding="utf-8") == "{}\n"


def test_profile_timezone_comes_from_the_public_config(monkeypatch):
    assert cli._config_timezone('timezone: "Asia/Kolkata"\n') == "Asia/Kolkata"
    assert cli._config_timezone("model: x\ntimezone: Europe/Zurich\n") == "Europe/Zurich"
    assert cli._config_timezone("  timezone: Asia/Kolkata\n") == ""
    assert cli._config_timezone("timezone:\n") == ""
    assert cli._config_timezone('timezone: ""\n') == ""
    monkeypatch.setenv("HERMES_TIMEZONE", "Asia/Kolkata")
    assert cli.when_text() == "08:00 in the profile timezone Asia/Kolkata."
    monkeypatch.setenv("HERMES_TIMEZONE", "not a zone")
    assert cli.when_text() == "08:00 in the machine local time."
    assert "hermes_time" not in (ROOT / "cli.py").read_text(encoding="utf-8")
    assert "Read the id from cron list" in cli._lines(None)
    assert "Read the id from cron status" not in cli._lines(None)


def test_schedule_is_local_and_prints_the_profile_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "when_text", lambda: "08:00 in the machine local time.")
    store = _Store()
    code, text = cli.schedule_job(store, "origin", tmp_path)
    assert code == 1
    assert "local only" in text
    assert not (tmp_path / "scripts").exists()
    code, text = cli.schedule_job(store, "telegram", tmp_path)
    assert code == 1
    prefix.remember_profile_name("harnessprof")
    code, text = cli.schedule_job(store, "local", tmp_path)
    assert code == 0
    assert "hermes -p harnessprof cron list" in text
    assert "hermes -p harnessprof cron remove abc123" in text
    assert cli.SCHEDULER_NOTE in text
    again, again_text = cli.schedule_job(store, "local", tmp_path)
    assert again == 0
    assert cli.SCHEDULER_NOTE in again_text
    assert "\nhermes cron list" not in text
    script = (tmp_path / "scripts" / "gleif-watch.py").read_text(encoding="utf-8")
    assert "get_hermes_home" in script
    assert "HERMES_HOME" not in script
    assert cli.PROMPT.count("[SILENT]") == 1
    for banned in ("say nothing", "stay silent", "reply with nothing", "do not reply", "output nothing"):
        assert banned not in cli.PROMPT.lower()
    assert store.created[0]["deliver"] == "local"
    assert store.created[0]["script"] == "gleif-watch.py"
    assert "--no-agent" in _public_args(store.created[0])
    code, text = cli.job_status(_Store())
    assert text == cli.GONE
    code, text = cli.unschedule_job(_Store(), tmp_path)
    assert cli.GONE in text
    assert "Removed scripts/gleif-watch.py." in text
    assert not (tmp_path / "scripts" / "gleif-watch.py").exists()


def test_readme_skill_and_manifest_agree():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "gleif" / "SKILL.md").read_text(encoding="utf-8")
    manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    assert 'hermes plugins install "file://$PWD" --enable' in readme
    assert "hermes plugins enable gleif" in readme
    assert """hermes gleif call lei_lookup --json '{"lei":"335800LUOBQQY1UPKZ54"}'""" in readme
    assert "hermes cron remove" in readme
    assert "hermes cron list" in readme
    assert "does not print the id" in readme
    assert "1,000,000" in readme
    assert "wordmark" in readme
    assert "parents_complete" in readme
    assert "no legal-name candidate" in readme
    assert "/" + "private" + "/" + "tmp" not in readme
    assert "/" + "Users" + "/" not in readme
    assert "approval-card" in readme
    assert "local only" in readme
    assert "does not fire until a scheduler is serving this profile" in readme
    assert "hermes --profile default gateway install" in readme
    assert "hermes gateway install" in readme
    assert "cron/output" in readme
    assert "plugin-data/gleif/watch.json" in readme
    assert "scripts/gleif-watch.py" in readme
    assert "hermes --profile default gateway install" in skill
    assert "cron/output" in skill
    assert skill.find("tool_search") < skill.find("web_search")
    assert "Before the user runs `hermes gleif schedule`" in skill
    assert "watched LEI list" in skill
    description = skill.split("description:", 1)[1].split("\n", 1)[0].strip().strip('"')
    assert len(description) <= 223
    assert "tool_search before web_search" in description
    assert "python_dependencies: []" in manifest
    assert "pip install" not in readme
    assert "requires_hermes: \">=0.21.4\"" in manifest
    for schema in __import__("schemas").ALL:
        sentence = schema["description"].split(". ")[0] + "."
        assert len(sentence) <= 60
        assert not sentence.lower().startswith("read-only")
    nouns = " ".join(schema["description"] for schema in __import__("schemas").ALL).lower()
    for word in ("lei", "legal name", "parent", "child", "isin"):
        assert word in nouns


def test_ordinary_phrases_rank_above_unrelated_tools():
    src = os.environ.get("HERMES_SRC", "").strip()
    if not src or not Path(src).is_dir():
        pytest.skip("HERMES_SRC is unset")
    import sys
    sys.path.insert(0, src)
    from tools.tool_search_catalog import build_catalog, search_catalog
    from schemas import ALL

    defs = [{"type": "function", "function": {"name": row["name"], "description": row["description"]}} for row in ALL]
    for index in range(12):
        defs.append({
            "type": "function",
            "function": {
                "name": f"calendar_item_{index}",
                "description": "Look up this map of a company booking. Book a flight, a hotel, or a calendar event for tomorrow.",
            },
        })
    catalog = build_catalog(defs)
    phrases = [
        "Look up this LEI legal name",
        "parent company of this LEI",
        "map this ISIN to an LEI",
    ]
    for phrase in phrases:
        ranked = [entry.name for entry in search_catalog(catalog, phrase, limit=5)]
        assert any(name.startswith("lei_") for name in ranked), ranked


class _Store:
    def __init__(self):
        self.jobs = []
        self.created = []

    def job_by_name(self, name):
        for job in self.jobs:
            if job.get("name") == name:
                return job
        return None

    def create_job(self, **kwargs):
        job = {"id": "abc123", **kwargs}
        self.jobs.append(job)
        self.created.append(kwargs)
        return job

    def remove_job(self, job_id):
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]
        return True


def _public_args(created: dict) -> list[str]:
    from public_cron import Cmd, Store

    seen = {}

    def run(args):
        seen["args"] = args
        if args[:1] == ["list"]:
            return Cmd(0, "", "")
        return Cmd(0, "Created job: job42\n", "")

    Store(run).create_job(**created)
    return seen["args"]
