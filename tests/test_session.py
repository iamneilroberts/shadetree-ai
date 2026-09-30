import json
from pathlib import Path

import pytest

from obd_reader.session import AdapterBusy, Config, NoAdapterError, Session

from conftest import ScriptedPort


def make(tmp_path, port="fake", **cfg):
    return Session(Config(port=port, home=tmp_path, **cfg),
                   port_factory=lambda: ScriptedPort({"0C": "1AF8"}))


def test_config_from_env():
    c = Config.from_env({"SHADETREE_PORT": "/dev/ttyUSB9", "SHADETREE_BAUD": "38400",
                         "SHADETREE_TIMEOUT": "3", "SHADETREE_HOME": "/tmp/x"})
    assert (c.port, c.baud, c.timeout, c.home) == ("/dev/ttyUSB9", 38400, 3.0, Path("/tmp/x"))
    d = Config.from_env({})
    assert d.port is None and d.baud == 115200 and d.timeout == 10.0 and d.home == Path(".")


def test_connection_initialises_the_adapter_and_records_a_transcript(tmp_path):
    s = make(tmp_path)
    with s.connection("unit") as t:
        t.send("010C")
    files = list((tmp_path / "transcripts").glob("*-unit.jsonl"))
    assert len(files) == 1
    lines = [json.loads(ln) for ln in files[0].read_text().splitlines()]
    assert [ln["tx"] for ln in lines][:5] == ["ATZ", "ATE0", "ATL0", "ATH0", "ATSP0"]
    assert lines[-1]["tx"] == "010C"


def test_no_port_configured_means_no_adapter_error_and_no_port_opened(tmp_path):
    opened = []
    s = Session(Config(port=None, home=tmp_path), port_factory=lambda: opened.append(1))
    with pytest.raises(NoAdapterError):
        with s.connection("x"):
            pass
    assert opened == []


def test_a_second_connection_while_one_is_open_fails_fast(tmp_path):  # Review Focus 3
    s = make(tmp_path)
    with s.connection("first"):
        with pytest.raises(AdapterBusy):
            with s.connection("second"):
                pass
    with s.connection("third"):  # released afterwards
        pass


def test_lock_is_released_when_the_body_raises(tmp_path):
    s = make(tmp_path)
    with pytest.raises(RuntimeError):
        with s.connection("boom"):
            raise RuntimeError("x")
    with s.connection("after"):
        pass


def test_raw_port_shares_the_lock_and_the_no_adapter_rule(tmp_path):
    s = make(tmp_path)
    with s.raw_port() as port:
        assert port is not None
        with pytest.raises(AdapterBusy):
            with s.connection("x"):
                pass
    with s.connection("y"):  # released
        pass
    with pytest.raises(NoAdapterError):
        with Session(Config(port=None, home=tmp_path), port_factory=lambda: ScriptedPort({})).raw_port():
            pass


def test_port_is_closed_after_use(tmp_path):
    closed = []

    class P(ScriptedPort):
        def close(self):
            closed.append(True)

    s = Session(Config(port="fake", home=tmp_path), port_factory=lambda: P({}))
    with s.connection("c"):
        pass
    assert closed == [True]
