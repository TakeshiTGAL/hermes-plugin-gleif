"""Failure objects. Each one is a literal so the type stays a fixed token."""

LEI_INVALID = {
    "ok": False,
    "error_type": "lei_invalid",
    "error": "The LEI failed the ISO 17442 check, so the API was not called.",
    "next_step": "Pass a 20-character LEI. This result does not name a parent.",
}

LEI_NOT_FOUND = {
    "ok": False,
    "error_type": "lei_not_found",
    "error": "The LEI record was not in the index.",
    "next_step": "Check the 20-character LEI. This result does not name a parent.",
}

NAME_INVALID = {
    "ok": False,
    "error_type": "name_invalid",
    "error": "The legal name is empty, too long, or contains a control character.",
    "next_step": "Pass the legal name as plain text up to 200 characters.",
}

ISIN_INVALID = {
    "ok": False,
    "error_type": "isin_invalid",
    "error": "The ISIN failed the ISO 6166 check, so the API was not called.",
    "next_step": "Pass a 12-character ISIN.",
}

QUERY_INVALID = {
    "ok": False,
    "error_type": "query_invalid",
    "error": "The name fragment is empty, too long, or contains a control character.",
    "next_step": "Pass a legal name fragment up to 80 characters.",
}

ARGS_INVALID = {
    "ok": False,
    "error_type": "args_invalid",
    "error": "The arguments are outside the accepted set.",
    "next_step": "Pass the fields named in the tool description and no others.",
}

PAGE_REFUSED = {
    "ok": False,
    "error_type": "page_refused",
    "error": "The page number is outside 1, 2, and 3.",
    "next_step": "Pass page 1, 2, or 3. Later pages stay unread.",
}

RATE_LIMITED = {
    "ok": False,
    "error_type": "rate_limited",
    "error": "The API returned 429.",
    "next_step": "Wait a minute. The published limit is 60 requests a minute per user. Nothing was inferred.",
}

UPSTREAM_DOWN = {
    "ok": False,
    "error_type": "upstream_down",
    "error": "The API did not answer.",
    "next_step": "Try the same call later. Nothing was inferred.",
}

UPSTREAM_ERROR = {
    "ok": False,
    "error_type": "upstream_error",
    "error": "The API returned an error status.",
    "next_step": "Try the same call later. Nothing was inferred.",
}

REDIRECTED = {
    "ok": False,
    "error_type": "redirected",
    "error": "The API redirected, and the redirect was not followed.",
    "next_step": "Try the same call later. No other host was contacted.",
}

TRUNCATED = {
    "ok": False,
    "error_type": "truncated",
    "error": "The response exceeded 1,000,000 bytes and was not read to the end.",
    "next_step": "Narrow the query. Completeness is unknown.",
}

BAD_BODY = {
    "ok": False,
    "error_type": "bad_body",
    "error": "The response was not a JSON object.",
    "next_step": "Try the same call later. Nothing was inferred.",
}

UNKNOWN_SHAPE = {
    "ok": False,
    "error_type": "unknown_shape",
    "error": "The response shape was outside the records this plugin reads.",
    "next_step": "Try the same call later. Nothing was inferred.",
}

UNKNOWN_TOOL = {
    "ok": False,
    "error_type": "unknown_tool",
    "error": "That tool is not registered.",
    "next_step": "Call lei_lookup, lei_parents, lei_children, lei_search, or lei_isin.",
}

WATCH_FULL = {
    "ok": False,
    "error_type": "watch_full",
    "error": "The watch list already holds 10 LEIs.",
    "next_step": "Remove one LEI, then add this one.",
}

WATCH_UNREADABLE = {
    "ok": False,
    "error_type": "watch_unreadable",
    "error": "The watch file was not read.",
    "next_step": "Move the file aside and add the LEIs again.",
}

WATCH_REFUSED = {
    "ok": False,
    "error_type": "watch_refused",
    "error": "The watch file was not written.",
    "next_step": "Use a real directory that is not a symlink.",
}
