"""Optional add-ons. An installed package registers an object under the entry-point group
`shadetree_ai.plugins`; every hook on that object is optional:

    cli(sub)               add argparse subcommands to `shadetree-ai`
    mcp_tools(session)     -> {name: PluginTool}, registered after the public tools
    mcp_instructions()     -> str appended to the MCP server instructions
    page_extension()       -> PageExtension spliced into the console page at its markers
    console_routes(hub)    -> ({GET path: fn(query)}, {POST path: fn(body)}), behind the console's guard

With no add-on installed nothing changes. SHADETREE_NO_PLUGINS=1 skips loading (the test suite sets it)."""
import os
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Callable

GROUP = "shadetree_ai.plugins"
MARKERS = {"tabs": b"<!--plugin-tabs-->", "panels": b"<!--plugin-panels-->", "js": b"/*plugin-js*/"}


@dataclass(frozen=True)
class PageExtension:
    tabs: str = ""
    panels: str = ""
    js: str = ""


@dataclass(frozen=True)
class PluginTool:
    fn: Callable[..., Any]
    read_only: bool = True
    destructive: bool = False


def load_plugins() -> list[Any]:
    if os.environ.get("SHADETREE_NO_PLUGINS") == "1":
        return []
    return [ep.load() for ep in sorted(entry_points(group=GROUP), key=lambda ep: ep.name)]


def extend_page(page: bytes, extensions: list[PageExtension]) -> bytes:
    """Insert each extension's parts after the page's markers. The JS lands inside the page's one
    script, so the CSP hash computed afterwards covers it; a part that opens or closes a script is refused."""
    if not extensions:
        return page
    for part, marker in MARKERS.items():
        text = "".join(getattr(e, part) for e in extensions)
        if "<script" in text.lower() or "</script" in text.lower():
            raise ValueError(f"plugin {part} may not open or close a script element")
        if page.count(marker) != 1:
            raise ValueError(f"console page marker {marker.decode()} is missing or repeated")
        page = page.replace(marker, marker + text.encode("utf-8"))
    return page


def collect_routes(plugins: list[Any], hub: Any, reserved: set[str]) -> tuple[dict[str, Callable], dict[str, Callable]]:
    get: dict[str, Callable] = {}
    post: dict[str, Callable] = {}
    for p in plugins:
        hook = getattr(p, "console_routes", None)
        if hook is None:
            continue
        g, ps = hook(hub)
        for table, new in ((get, g), (post, ps)):
            for path, fn in new.items():
                if not path.startswith("/api/") or path in reserved or path in get or path in post:
                    raise ValueError(f"plugin route {path!r} is not a free /api/ path")
                table[path] = fn
    return get, post


def collect_tools(plugins: list[Any], session: Any, reserved: set[str]) -> dict[str, PluginTool]:
    out: dict[str, PluginTool] = {}
    for p in plugins:
        hook = getattr(p, "mcp_tools", None)
        if hook is None:
            continue
        for name, tool in hook(session).items():
            if name in reserved or name in out:
                raise ValueError(f"plugin tool {name!r} collides with an existing tool")
            out[name] = tool
    return out
