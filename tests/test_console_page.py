import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import pytest

HTML = resources.files("obd_reader.web").joinpath("console.html").read_text(encoding="utf-8")


def test_page_is_self_contained_with_no_external_urls():
    assert not re.search(r"https?://", HTML)
    assert "<script src" not in HTML and "<link " not in HTML


def test_every_view_button_has_a_matching_section():
    views = set(re.findall(r'data-view="([a-z0-9]+)"', HTML))
    assert {"v1", "v2", "v3"} <= views
    for view in views:
        assert f'id="{view}"' in HTML


def test_required_controls_exist_and_no_simulator_is_baked_in():
    for element_id in ("chipLive", "chipConn", "pause", "save", "msg", "simctl", "rpmGauge", "c1trims",
                       "s_trim", "results", "verdict", "go_idle", "go_rev"):
        assert f'id="{element_id}"' in HTML, element_id
    assert "function tick" not in HTML  # the mock's fake data generator is gone
    for route in ("/api/state", "/api/start", "/api/stop", "/api/save"):
        assert route in HTML


def _section(view: str, nxt: str) -> str:
    return HTML[HTML.index(f'id="{view}"'):HTML.index(f'id="{nxt}"')]


def test_every_multi_line_chart_has_a_legend_naming_each_line():
    # Cockpit: the fuel-trim chart draws four lines (bank 1/2 x short/long term) and must say which is which
    v1 = _section("v1", "v2")
    legend = re.search(r'id="c1legend".*?</div>', v1, re.S)
    assert legend, "cockpit trim chart needs a legend"
    for label in ("STFT bank 1", "LTFT bank 1", "STFT bank 2", "LTFT bank 2"):
        assert label in legend.group(0), label
    assert v1.index('id="c1legend"') < v1.index('id="c1trims"'), "legend goes above the chart"
    # Scope: the same trims and the airflow/coolant chart keep theirs
    v2 = _section("v2", "v3")
    assert v2.count('class="legend"') >= 2 and "LTFT b2" in v2 and "coolant" in v2


def test_the_legend_distinguishes_lines_by_pattern_not_only_by_colour():
    legend = re.search(r'id="c1legend".*?</div>', _section("v1", "v2"), re.S).group(0)
    assert legend.count("solid") >= 2 and legend.count("dashed") >= 2


def test_page_states_it_is_read_only_and_marks_the_playbook_unreviewed():
    assert "READ-ONLY" in HTML and "unreviewed" in HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_logic_runs_against_a_fake_dom_and_scripted_server_states():
    """Runs the page's real <script> under Node: timed captures, both verdicts, start request, run reset."""
    page = str(resources.files("obd_reader.web").joinpath("console.html"))
    script = str(Path(__file__).parent / "js" / "page_logic_test.js")
    r = subprocess.run(["node", script, page], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "page logic OK" in r.stdout, r.stdout + r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_inline_script_parses(tmp_path):
    js = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)
    f = tmp_path / "console.js"
    f.write_text(js)
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
