from types import SimpleNamespace

import pytest

from obd_reader import plugins
from obd_reader.plugins import PageExtension, PluginTool, collect_routes, collect_tools, extend_page, load_plugins
from obd_reader.session import AdapterBusy, Config, Session

PAGE = b"<nav><!--plugin-tabs--></nav><main><!--plugin-panels--></main><script>(function(){/*plugin-js*/})();</script>"


def _eps(*objs):
    def entry_points(group):
        if group != plugins.GROUP:
            return []
        return [SimpleNamespace(name=f"p{i}", load=lambda o=o: o) for i, o in enumerate(objs)]
    return entry_points


def test_load_plugins_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(plugins, "entry_points", _eps(object()))
    assert load_plugins() == []  # conftest sets SHADETREE_NO_PLUGINS=1


def test_load_plugins_loads_registered_objects(monkeypatch):
    monkeypatch.delenv("SHADETREE_NO_PLUGINS")
    obj = object()
    monkeypatch.setattr(plugins, "entry_points", _eps(obj))
    assert load_plugins() == [obj]


def test_extend_page_without_extensions_is_byte_identical():
    assert extend_page(PAGE, []) is PAGE


def test_extend_page_inserts_after_each_marker():
    out = extend_page(PAGE, [PageExtension(tabs="<b>T</b>", panels="<section id='vx'></section>", js="var x=1;")])
    assert b"<!--plugin-tabs--><b>T</b>" in out
    assert b"<!--plugin-panels--><section id='vx'></section>" in out
    assert b"/*plugin-js*/var x=1;})();</script>" in out


@pytest.mark.parametrize("part", ["tabs", "panels", "js"])
def test_extend_page_refuses_script_tags(part):
    with pytest.raises(ValueError):
        extend_page(PAGE, [PageExtension(**{part: "</script><script>alert(1)"})])


def test_extend_page_refuses_a_page_without_markers():
    with pytest.raises(ValueError):
        extend_page(b"<script></script>", [PageExtension(js="1")])


def test_routes_must_be_free_api_paths():
    taken = SimpleNamespace(console_routes=lambda hub: ({"/api/state": lambda q: {}}, {}))
    with pytest.raises(ValueError):
        collect_routes([taken], hub=None, reserved={"/api/state"})
    outside = SimpleNamespace(console_routes=lambda hub: ({"/x": lambda q: {}}, {}))
    with pytest.raises(ValueError):
        collect_routes([outside], hub=None, reserved=set())


def test_routes_collect_get_and_post():
    p = SimpleNamespace(console_routes=lambda hub: ({"/api/x/a": "g"}, {"/api/x/b": "p"}))
    assert collect_routes([p, object()], hub=None, reserved=set()) == ({"/api/x/a": "g"}, {"/api/x/b": "p"})


def test_tools_refuse_name_collisions():
    p = SimpleNamespace(mcp_tools=lambda s: {"read_pid": PluginTool(fn=lambda: 1)})
    with pytest.raises(ValueError):
        collect_tools([p], session=None, reserved={"read_pid"})


def test_exclusive_holds_the_adapter_lock(tmp_path):
    s = Session(Config(port="fake", home=tmp_path))
    with s.exclusive():
        with pytest.raises(AdapterBusy):
            with s.exclusive():
                pass
    with s.exclusive():  # released again
        pass


import asyncio

import obd_reader.__main__ as main_mod
from obd_reader.mcp_server import INSTRUCTIONS, build_server, server_instructions
from obd_reader.tools import TOOL_NAMES


def test_mcp_server_registers_plugin_tools_with_their_annotations(tmp_path):
    def pro_ping() -> str:
        """Say pong."""
        return "pong"

    p = SimpleNamespace(mcp_tools=lambda s: {"pro_ping": PluginTool(fn=pro_ping, read_only=False)})
    srv = build_server(Session(Config(port=None, home=tmp_path)), plugins=[p])
    by_name = {t.name: t for t in asyncio.run(srv.list_tools())}
    assert set(by_name) == set(TOOL_NAMES) | {"pro_ping"}
    assert by_name["pro_ping"].annotations.read_only_hint is False
    assert by_name["read_pid"].annotations.read_only_hint is True


def test_mcp_server_without_plugins_is_unchanged(tmp_path):
    srv = build_server(Session(Config(port=None, home=tmp_path)), plugins=[])
    assert {t.name for t in asyncio.run(srv.list_tools())} == set(TOOL_NAMES)


def test_server_instructions_append_plugin_text():
    assert server_instructions([]) == INSTRUCTIONS
    assert server_instructions([SimpleNamespace(mcp_instructions=lambda: "EXTRA")]) == INSTRUCTIONS + "\n\nEXTRA"


def test_cli_gains_plugin_subcommands(monkeypatch):
    def cli(sub):
        sp = sub.add_parser("pro")
        sp.set_defaults(func=lambda a: 7)

    monkeypatch.setattr(main_mod, "load_plugins", lambda: [SimpleNamespace(cli=cli)])
    assert main_mod.main(["pro"]) == 7


import re
from importlib import resources

from obd_reader.console import ConsoleServer
from obd_reader.hub import LiveHub
from obd_reader.simulator import SimPort
from test_console import call


def _plugin():
    return SimpleNamespace(
        page_extension=lambda: PageExtension(
            tabs='<button class="vbtn" data-view="vx" role="tab">X</button>',
            panels='<section class="view" id="vx" role="tabpanel"></section>',
            js="var plug=1;"),
        console_routes=lambda hub: ({"/api/x/ping": lambda q: {"pong": True}},
                                    {"/api/x/echo": lambda body: {"got": body.get("v")}}))


def _server(tmp_path, plugins):
    sim = SimPort("rich")
    session = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(session, sim=sim)
    server = ConsoleServer(hub, token="tok123", plugins=plugins)
    server.start()
    return server, hub


def test_page_without_plugins_is_the_file(tmp_path):
    server, hub = _server(tmp_path, [])
    try:
        html, _ = server._page()
        assert html == resources.files("obd_reader.web").joinpath("console.html").read_bytes()
    finally:
        hub.stop()
        server.stop()


def test_plugin_page_parts_land_inside_the_hashed_script(tmp_path):
    server, hub = _server(tmp_path, [_plugin()])
    try:
        html, csp = server._page()
        script = re.search(rb"<script>(.*?)</script>", html, re.S).group(1)
        assert b"var plug=1;" in script
        assert b'id="vx"' in html and b'data-view="vx"' in html
        assert html.count(b"<script") == 1
    finally:
        hub.stop()
        server.stop()


def test_plugin_routes_answer_behind_the_token(tmp_path):
    server, hub = _server(tmp_path, [_plugin()])
    try:
        assert call(server, "GET", "/api/x/ping") == (200, {"pong": True})
        assert call(server, "POST", "/api/x/echo", {"v": 3}) == (200, {"got": 3})
        assert call(server, "GET", "/api/x/ping", token="wrong")[0] == 401
        assert call(server, "POST", "/api/x/ping", {})[0] == 405
    finally:
        hub.stop()
        server.stop()


def _busy():
    from obd_reader.session import AdapterBusy
    raise AdapterBusy("adapter busy")


def test_plugin_get_busy_is_409(tmp_path):
    server, hub = _server(tmp_path, [SimpleNamespace(
        console_routes=lambda hub: ({"/api/x/busy": lambda q: _busy()}, {}))])
    try:
        assert call(server, "GET", "/api/x/busy")[0] == 409
    finally:
        hub.stop()
        server.stop()


def test_plugin_post_missing_key_is_400(tmp_path):
    server, hub = _server(tmp_path, [SimpleNamespace(
        console_routes=lambda hub: ({}, {"/api/x/need": lambda body: {"v": body["missing"]}}))])
    try:
        assert call(server, "POST", "/api/x/need", {})[0] == 400
    finally:
        hub.stop()
        server.stop()
