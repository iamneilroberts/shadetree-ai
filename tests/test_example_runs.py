"""Guard: examples/runs/ is public. Every run there must load, carry a valid label if it has one, and hold no
VIN-shaped text or vin field. Test VINs only ever come from obd_reader.vin.with_check_digit."""
import json
import re
import subprocess
import shutil
from pathlib import Path

import pytest

from obd_reader.replay_run import clean_meta, load_run, read_run_file

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "runs"
HONDA = "2026-09-30T21-32-56Z-drive-rebuilt.json"
_VIN_SHAPED = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])")


def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


def problems(folder: Path) -> dict[str, str]:
    out = {}
    for p in sorted(folder.iterdir()):
        text = p.read_text(encoding="utf-8")
        if _VIN_SHAPED.search(text.upper()):
            out[p.name] = "VIN-shaped text"
            continue
        if p.name == "README.md":
            continue
        try:
            obj = read_run_file(folder, p.name)
            load_run(obj)
            if "meta" in obj:
                clean_meta(obj["meta"])
        except (ValueError, OSError) as e:
            out[p.name] = f"not a valid run: {e}"
            continue
        if any(isinstance(k, str) and "vin" in k.lower() for k in _keys(obj)):
            out[p.name] = "has a vin field"
    return out


def test_every_example_run_loads_and_holds_no_vin():
    runs = [p for p in EXAMPLES.iterdir() if p.suffix == ".json"]
    assert runs, "examples/runs should hold at least one run"
    assert (EXAMPLES / "README.md").is_file()
    assert problems(EXAMPLES) == {}


def test_the_guard_catches_a_vin_a_vin_field_and_a_broken_run(tmp_path):
    from obd_reader.vin import with_check_digit

    good = json.loads((EXAMPLES / HONDA).read_text())
    vin = with_check_digit("5FPYK3F5?RB999999")
    (tmp_path / "ok.json").write_text(json.dumps(good))
    (tmp_path / "leak.json").write_text(json.dumps({**good, "note": vin.lower()}))
    (tmp_path / "field.json").write_text(json.dumps({**good, "vehicle": {"vin": None}}))
    (tmp_path / "broken.json").write_text(json.dumps({"kind": "live_run"}))
    (tmp_path / "badmeta.json").write_text(json.dumps({**good, "meta": {"make": "x"}}))
    assert problems(tmp_path) == {"leak.json": "VIN-shaped text", "field.json": "has a vin field",
                                  "broken.json": "not a valid run: a run needs 1 to 64 readings",
                                  "badmeta.json": "not a valid run: model must be 1 to 40 printable characters"}


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_examples_are_tracked_not_ignored():
    r = subprocess.run(["git", "check-ignore", "-q", f"examples/runs/{HONDA}"], cwd=ROOT)
    assert r.returncode == 1, "examples/runs must not be gitignored"


def test_the_honda_example_is_labelled_listed_and_replays_without_the_adapter(tmp_path):
    import http.client

    from obd_reader.console import ConsoleServer
    from obd_reader.hub import LiveHub
    from obd_reader.session import Config, Session

    def no_adapter():
        raise AssertionError("a replay must never open the adapter")

    hub = LiveHub(Session(Config(port="/dev/null-never", home=tmp_path, timeout=0.5), port_factory=no_adapter))
    server = ConsoleServer(hub, token="tok", examples_dir=EXAMPLES)
    server.start()

    def call(method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        c.request(method, path + "?t=tok", body=json.dumps(body) if body is not None else None,
                  headers={"Host": f"127.0.0.1:{server.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        out = r.status, json.loads(r.read())
        c.close()
        return out

    try:
        status, body = call("GET", "/api/runs")
        assert status == 200
        honda = next(r for r in body["examples"] if r["name"] == HONDA)
        assert honda["meta"] == {"make": "Honda", "model": "Ridgeline", "year": 2024, "title": "Ridgeline 6 min drive"}
        assert honda["time"] == "2026-09-30T21:32:56Z" and 300 < honda["duration"] < 400
        assert all(r["name"] != HONDA for r in body["runs"]), "the example is not one of My runs"
        assert call("POST", "/api/replay", {"source": "examples", "name": HONDA}) == (200, {"ok": True})
        st = call("GET", "/api/state")[1]
        assert st["replay"]["name"] == HONDA and st["adapter"]["ati"] == "replay"
        assert "0C" in st["channels"]
        assert call("POST", "/api/replay/control", {"action": "exit"})[0] == 200
        assert not (tmp_path / "runs").exists(), "a replay writes nothing"
    finally:
        hub.stop()
        server.stop()
