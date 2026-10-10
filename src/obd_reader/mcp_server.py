"""MCP front end. Every tool is registered read-only; the tool list is the reviewed
set in tools.TOOL_NAMES and no tool takes a command string."""
import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from obd_reader.plugins import collect_tools, load_plugins
from obd_reader.session import Config, Session
from obd_reader.tools import TOOL_NAMES, build_tools

INSTRUCTIONS = (
    "shadetree-ai is a READ-ONLY OBD-II assistant. It can read codes, freeze frames, readiness "
    "monitors, live data and Mode 06 test results; it can never clear codes, write to an ECU or "
    "run actuator tests, and no tool accepts a raw command. If asked to clear codes, say so and "
    "tell the user to use their own scan tool after the repair. Cite a tool result or a reference "
    "record for every diagnostic claim; label anything else 'general knowledge, unverified'. "
    "Live tools need the car parked with the ignition on; offline tools read saved snapshots."
)


def _surface_errors(fn):
    """mcp 2.x hides an ordinary exception's message behind 'Error executing tool'; ToolError
    keeps it, so Claude sees 'adapter is busy' or 'not a 2-digit hex PID' and can react."""

    @functools.wraps(fn)  # keeps the signature, so the generated input schema is unchanged
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, RuntimeError, LookupError, OSError) as e:
            raise ToolError(str(e)) from None

    return wrapper


def server_instructions(plugins: list) -> str:
    return INSTRUCTIONS + "".join("\n\n" + p.mcp_instructions() for p in plugins if hasattr(p, "mcp_instructions"))


def build_server(session: Session, plugins: list | None = None) -> MCPServer:
    plugins = load_plugins() if plugins is None else plugins
    server = MCPServer("shadetree-ai", instructions=server_instructions(plugins))
    tools = build_tools(session)
    assert set(tools) == set(TOOL_NAMES), "tool registry drifted from the reviewed set"
    for name, fn in tools.items():
        server.tool(
            name=name,
            annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
        )(_surface_errors(fn))
    for name, tool in collect_tools(plugins, session, set(tools)).items():
        server.tool(
            name=name,
            annotations=ToolAnnotations(read_only_hint=tool.read_only, destructive_hint=tool.destructive,
                                        open_world_hint=False),
        )(_surface_errors(tool.fn))
    return server


def main() -> None:
    build_server(Session(Config.from_env())).run()


if __name__ == "__main__":
    main()
