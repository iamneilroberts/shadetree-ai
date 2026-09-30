import pytest

from obd_reader.live import (
    MAX_POINTS, LiveLimitError, downsample, sample, summarize, validate_pids,
)
from obd_reader.snapshot import Series
from obd_reader.transport import Transport

from conftest import FakeClock, ScriptedPort


def run(pids, seconds, hz=2.0, data=None):
    port = ScriptedPort(data or {"0C": "1AF8", "05": "7B", "06": "80"})
    clk = FakeClock()
    ls = sample(Transport(port), pids, seconds, hz=hz, clock=clk.now, sleep=clk.sleep)
    return ls, port


def test_sample_polls_each_pid_every_tick_and_decodes():
    ls, port = run(["0C", "05"], seconds=2, hz=2)
    assert [t for t, _ in ls.series["0C"].samples] == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert {v for _, v in ls.series["0C"].samples} == {1726.0}
    assert {v for _, v in ls.series["05"].samples} == {83}
    assert ls.series["0C"].name == "engine_rpm" and ls.series["0C"].unit == "rpm"
    assert ls.duration_s == 2 and ls.rate_hz == 2
    assert port.writes and all(c.startswith("01") and len(c) == 4 for c in port.writes)


def test_pid_without_data_yields_an_empty_series_not_an_error():
    ls, _ = run(["0C", "0D"], seconds=1, hz=1, data={"0C": "1AF8"})
    assert ls.series["0D"].samples == [] and len(ls.series["0C"].samples) == 2


@pytest.mark.parametrize(
    "pids",
    [[], ["0C"] * 2, ["0C\r04"], ["ZZ"], ["0c\n"], ["0C0"], ["FF"], [f"{i:02X}" for i in range(9)], [""], [None]],
)
def test_bad_pid_lists_are_refused_before_any_traffic(pids):
    port = ScriptedPort({})
    with pytest.raises(LiveLimitError):
        sample(Transport(port), pids, 1)
    assert port.writes == []


@pytest.mark.parametrize("seconds,hz", [(0, 2), (-1, 2), (121, 2), (10, 0), (10, 11), (10, -1), (10, 0.05), (1, 1e-6)])
def test_bad_duration_or_rate_is_refused_before_any_traffic(seconds, hz):
    port = ScriptedPort({"0C": "1AF8"})
    with pytest.raises(LiveLimitError):
        sample(Transport(port), ["0C"], seconds, hz=hz)
    assert port.writes == []


def test_validate_pids_normalises_case():
    assert validate_pids(["0c", "5c"]) == ["0C", "5C"]


def test_summarize_is_exact():
    s = Series(name="x", unit="%", samples=[(0.0, 1.0), (1.0, 3.0), (2.0, 2.0)])
    assert summarize(s) == {"n": 3, "min": 1.0, "max": 3.0, "mean": 2.0, "first": 1.0, "last": 2.0, "delta": 1.0}
    assert summarize(Series(name="x", samples=[])) == {"n": 0}


def test_downsample_keeps_endpoints_and_caps_points():  # Review Focus 5
    pts = [(float(i), float(i)) for i in range(1000)]
    out = downsample(pts)
    assert len(out) <= MAX_POINTS and out[0] == pts[0] and out[-1] == pts[-1]
    assert downsample(pts[:10]) == pts[:10]
