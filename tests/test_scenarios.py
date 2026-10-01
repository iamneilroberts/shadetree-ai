import json

import pytest

from obd_reader.scenarios import MAX_BYTES, load_scenarios, parse_scenarios


def doc(*scen):
    return json.dumps({"scenarios": list(scen)})


def sc(id="towing", name="Towing", gauges=None):
    return {"id": id, "name": name, "gauges": gauges if gauges is not None else [{"pid": "05"}]}


def test_valid_file_is_normalised():
    out = parse_scenarios(doc(sc(gauges=[{"pid": "0c", "form": "bar"}, {"pid": "05"}])))
    assert out == [{"id": "towing", "name": "Towing",
                    "gauges": [{"pid": "0C", "form": "bar"}, {"pid": "05", "form": "dial"}]}]


@pytest.mark.parametrize("text", [
    "not json",
    '{"scenarios": [{"id": "a", "name": "A", "gauges": [{"pid": "05", "lo": Infinity}]}]}',
    '{"scenarios": NaN}',
    "[]",
    '{"scenarios": [], "extra": 1}',
    doc(sc(gauges=[])),
    doc(sc(gauges=[{"pid": "05"}] * 9)),
    doc(sc(gauges=[{"pid": "constructor"}])),
    doc(sc(gauges=[{"pid": "7"}])),
    doc(sc(gauges=[{"pid": "05", "form": "pie"}])),
    doc(sc(gauges=[{"pid": "05", "lo": 0}])),
    doc(sc(id="Bad Id")),
    doc(sc(id="x" * 25)),
    doc(sc(name="")),
    doc(sc(name="x" * 25)),
    doc(sc(name="a\x00b")),
    doc(sc(), sc()),
    doc(*[sc(id="s%d" % i) for i in range(13)]),
])
def test_bad_files_are_refused_with_a_message(text):
    with pytest.raises(ValueError) as e:
        parse_scenarios(text)
    assert str(e.value)


def test_oversized_file_is_refused_before_parsing(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(" " * (MAX_BYTES + 1))
    with pytest.raises(ValueError, match="too large"):
        load_scenarios(p)


def test_load_reads_a_good_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(doc(sc()))
    assert load_scenarios(p)[0]["id"] == "towing"


# ---- route ------------------------------------------------------------------------------------------

from obd_reader.console import ConsoleServer  # noqa: E402
from obd_reader.hub import LiveHub  # noqa: E402
from obd_reader.session import Config, Session  # noqa: E402
from obd_reader.simulator import SimPort  # noqa: E402
from test_console import call  # noqa: E402

LIST = [{"id": "towing", "name": "Towing", "gauges": [{"pid": "05", "form": "dial"}]}]


@pytest.fixture
def servers(tmp_path):
    sim = SimPort("rich")
    hub = LiveHub(Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim), sim=sim)
    with_s = ConsoleServer(hub, token="tok123", scenarios=LIST)
    without = ConsoleServer(hub, token="tok123")
    with_s.start()
    without.start()
    yield with_s, without
    hub.stop()
    with_s.stop()
    without.stop()


def test_api_scenarios_returns_the_list_or_an_empty_one(servers):
    with_s, without = servers
    assert call(with_s, "GET", "/api/scenarios") == (200, {"scenarios": LIST})
    assert call(without, "GET", "/api/scenarios") == (200, {"scenarios": []})


def test_api_scenarios_is_guarded_and_get_only_exactly_like_help(servers):
    server, _ = servers
    help_status = call(server, "GET", "/api/help", token="wrong")[0]
    assert help_status != 200
    assert call(server, "GET", "/api/scenarios", token="wrong")[0] == help_status
    assert call(server, "GET", "/api/scenarios", token=None)[0] == call(server, "GET", "/api/help", token=None)[0] != 200
    evil = call(server, "GET", "/api/help", host="evil.example")[0]
    assert evil != 200 and call(server, "GET", "/api/scenarios", host="evil.example")[0] == evil
    assert call(server, "POST", "/api/help", body={})[0] == 405
    assert call(server, "POST", "/api/scenarios", body={})[0] == 405


# ---- CLI --------------------------------------------------------------------------------------------

def test_bad_scenarios_file_fails_the_console_command_with_a_message(tmp_path, capsys):
    from obd_reader.__main__ import main

    bad = tmp_path / "s.json"
    bad.write_text('{"scenarios": [{"id": "A", "name": "x", "gauges": []}]}')
    rc = main(["console", "--demo", "--http-port", "0", "--no-start", "--out-dir", str(tmp_path),
               "--scenarios", str(bad)])
    assert rc != 0
    assert f"--scenarios {bad}" in capsys.readouterr().err


def test_good_scenarios_file_reaches_the_server(tmp_path):
    from obd_reader.__main__ import build_parser, console_main

    good = tmp_path / "s.json"
    good.write_text(doc(sc()))
    args = build_parser().parse_args(["console", "--demo", "--http-port", "0", "--no-start",
                                      "--out-dir", str(tmp_path), "--scenarios", str(good)])
    svc = console_main(args, block=False)
    try:
        status, body = call(svc.server, "GET", "/api/scenarios", token=svc.server.token)
        assert status == 200 and body["scenarios"][0]["id"] == "towing"
    finally:
        svc.stop()
