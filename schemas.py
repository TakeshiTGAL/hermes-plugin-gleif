"""Tool schemas. Each description is one string so the first sentence stays intact."""

TOOLSET = "gleif"

LEI_LOOKUP = {
    "name": "lei_lookup",
    "description": "Look up one LEI record by LEI or legal name. Parents stay unread until lei_parents. The golden copy date is included when the response has one.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "lei": {"type": "string", "description": "20-character LEI."},
            "legal_name": {"type": "string", "description": "Legal name to filter. Returns candidates only."},
            "page": {"type": "integer", "description": "Page 1, 2, or 3 for a legal name filter."},
        },
    },
}

LEI_PARENTS = {
    "name": "lei_parents",
    "description": "Show official parent records for one LEI. The direct parent and the ultimate parent company are each an official record, a reporting exception, or an explicit miss. A 404 is not retried.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["lei"],
        "properties": {
            "lei": {"type": "string", "description": "20-character LEI of the child record."},
        },
    },
}

LEI_CHILDREN = {
    "name": "lei_children",
    "description": "List direct child LEI records for one LEI. One page is read. A later page stays unread, and an empty complete page is the only zero.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["lei"],
        "properties": {
            "lei": {"type": "string", "description": "20-character LEI."},
            "page": {"type": "integer", "description": "Page 1, 2, or 3."},
        },
    },
}

LEI_SEARCH = {
    "name": "lei_search",
    "description": "Search LEI legal names and list candidates. A fuzzy legal name returns name candidates only. A different legal name does not fetch a parent.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["q"],
        "properties": {
            "q": {"type": "string", "description": "Legal name fragment."},
        },
    },
}

LEI_ISIN = {
    "name": "lei_isin",
    "description": "Map an ISIN to an LEI or list ISINs for an LEI. One page is read. Parents stay unread.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "isin": {"type": "string", "description": "12-character ISIN."},
            "lei": {"type": "string", "description": "20-character LEI."},
            "page": {"type": "integer", "description": "Page 1, 2, or 3."},
        },
    },
}

ALL = [LEI_LOOKUP, LEI_PARENTS, LEI_CHILDREN, LEI_SEARCH, LEI_ISIN]
