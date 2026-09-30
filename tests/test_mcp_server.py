import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from obd_reader.mcp_server import INSTRUCTIONS, build_server
from obd_reader.session import Config, Session
from obd_reader.tools import TOOL_NAMES

from conftest import ScriptedPort


def server(tmp_path):
    return build_server(Session(Config(port="fake", home=tmp_path), port_factory=lambda: ScriptedPort({"0C": "1AF8"})))


def test_exactly_the_reviewed_tools_are_registered_and_all_read_only(tmp_path):
    tools = asyncio.run(server(tmp_path).list_tools())
    assert {t.name for t in tools} == set(TOOL_NAMES)
    for t in tools:
        assert t.annotations is not None and t.annotations.read_only_hint is True, t.name
        assert t.annotations.destructive_hint is False, t.name


def test_tool_schemas_never_expose_a_command_parameter(tmp_path):
    for t in asyncio.run(server(tmp_path).list_tools()):
        props = set((t.input_schema or {}).get("properties", {}))
        assert not props & {"cmd", "command", "raw", "hex", "at", "payload", "data"}, t.name


def test_a_tool_call_round_trips_through_the_server(tmp_path):
    res = asyncio.run(server(tmp_path).call_tool("read_pid", {"pid": "0C"}))
    assert res.is_error is False
    assert json.loads(res.content[0].text)["value"] == 1726.0


def test_bad_arguments_surface_our_message_as_a_tool_error(tmp_path):
    # In mcp 2.x a plain ValueError is hidden behind "Error executing tool"; ToolError keeps the message.
    with pytest.raises(ToolError) as e:
        asyncio.run(server(tmp_path).call_tool("read_pid", {"pid": "0C\r04"}))
    assert "2-digit hex PID" in str(e.value)


def test_adapter_busy_reaches_the_caller_readably(tmp_path):
    s = Session(Config(port="fake", home=tmp_path), port_factory=lambda: ScriptedPort({"0C": "1AF8"}))
    with s.connection("holder"):
        with pytest.raises(ToolError) as e:
            asyncio.run(build_server(s).call_tool("read_pid", {"pid": "0C"}))
    assert "busy" in str(e.value).lower()


def test_no_adapter_configured_is_a_readable_error(tmp_path):
    srv = build_server(Session(Config(port=None, home=tmp_path)))
    with pytest.raises(ToolError) as e:
        asyncio.run(srv.call_tool("adapter_info", {}))
    assert "SHADETREE_PORT" in str(e.value)


def test_schemas_survive_the_error_wrapper(tmp_path):
    by_name = {t.name: t for t in asyncio.run(server(tmp_path).list_tools())}
    assert set(by_name["read_pid"].input_schema["properties"]) == {"pid"}
    assert set(by_name["live_data"].input_schema["properties"]) == {"pids", "seconds", "hz", "conditions"}


def test_instructions_state_the_read_only_and_grounding_contracts():
    assert "read-only" in INSTRUCTIONS.lower() and "never clear" in INSTRUCTIONS.lower()
    assert "general knowledge, unverified" in INSTRUCTIONS
