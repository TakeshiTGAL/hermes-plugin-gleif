"""LEI Record. Official parent records, reporting exceptions, and an explicit miss."""
from pathlib import Path


def make_handler(name):
    """Hermes accepts a string tool result. A dict becomes tool_result_contract."""

    def _run(args, **_kwargs):
        if __package__:
            from .service import dump, invoke
        else:
            from service import dump, invoke
        return dump(invoke(name, args or {}))

    return _run


_SKILL_DESCRIPTION = (
    "Official LEI records and parents. Use tool_search before web_search, then tool_call lei_lookup. "
    "A parent is an official record, a reporting exception, or an explicit miss. Copy next_step."
)


def register(ctx) -> None:
    if __package__:
        from .cli import handle, setup_parser
        from .prefix import remember_profile_name
        from .schemas import ALL, TOOLSET
        from .service import TOOLS
    else:
        from cli import handle, setup_parser
        from prefix import remember_profile_name
        from schemas import ALL, TOOLSET
        from service import TOOLS

    try:
        reported = ctx.profile_name
    except Exception:
        reported = None
    remember_profile_name(reported)

    for schema in ALL:
        if schema["name"] not in TOOLS:
            continue
        ctx.register_tool(
            name=schema["name"],
            toolset=TOOLSET,
            schema=schema,
            handler=make_handler(schema["name"]),
        )
    ctx.register_cli_command(
        name="gleif",
        help="Look up an LEI record and watch one morning status",
        setup_fn=setup_parser,
        handler_fn=handle,
        description="Local commands for an LEI record and the morning watch.",
    )
    try:
        ctx.register_skill(
            "gleif",
            Path(__file__).resolve().parent / "skills" / "gleif" / "SKILL.md",
            description=_SKILL_DESCRIPTION,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).warning("gleif skill was not registered", exc_info=True)
