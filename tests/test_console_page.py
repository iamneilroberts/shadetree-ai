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
    assert {"v0", "v3", "v4", "v5", "v6"} <= views
    assert "v1" not in views and "v2" not in views
    for view in views:
        assert f'id="{view}"' in HTML


def test_required_controls_exist_and_no_simulator_is_baked_in():
    for element_id in ("unitsBtn", "replayBtn", "replayPanel", "rp_runs", "rp_load", "rp_file", "rp_err", "replayBanner", "rbar", "rb_restart", "rb_play", "rb_speed", "rb_seek", "rb_time", "rb_exit",
                       "chipLive", "chipConn", "chipCar", "chipLamp", "chipCodes", "o_tiles", "o_attn", "o_note", "helpPanel", "pause", "save", "msg", "simctl",
                       "results", "verdict", "go_idle", "go_rev"):
        assert f'id="{element_id}"' in HTML, element_id
    assert "function tick" not in HTML  # the mock's fake data generator is gone
    for route in ("/api/state", "/api/start", "/api/stop", "/api/save"):
        assert route in HTML


def test_page_has_no_read_only_banner_and_marks_the_playbook_unreviewed():
    assert "unreviewed" in HTML
    assert "READ-ONLY" not in HTML and "cannot send" not in HTML


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


def test_handheld_frame_has_a_fixed_size_so_switching_modes_never_resizes_it():
    frame = re.search(r"\.retro \.hh \{([^}]*)\}", HTML).group(1)
    assert "width: 390px" in frame and "height: 780px" in frame
    body = re.search(r"\.retro \.hh-body \{([^}]*)\}", HTML).group(1)
    assert "flex: 1" in body and "overflow-y: auto" in body  # long content scrolls inside the frame
    assert re.findall(r'<div class="hh-pane" data-mode="(\w+)"', HTML) == ["codes", "live", "trims", "status"]


def test_phone_width_hides_the_page_chrome_and_fills_the_screen_for_the_handheld_view():
    media = HTML[HTML.index("@media (max-width: 430px)"):]
    assert "#v5.is-active) .topbar" in media and "100dvh" in media


# ---- console stage 1: the features every stage must keep (spec "Retained features") ----------------
RETAINED = {
    "Capture all supported": ['id="capAll"', "body.capture = 'all'"],
    "Demo button": ['id="demoBtn"'],
    "Save run": ['id="save"', "/api/save"],
    "Replay picker (Examples / My runs) and ?example=": ['id="replayBtn"', 'id="replayPanel"', '<option value="examples">Examples</option>',
                                                         '<option value="mine">My runs</option>', 'id="rp_make"', 'id="rp_model"', 'id="rp_year"',
                                                         'id="rp_runs"', 'id="rp_load"', ".get('example')"],
    "Mode 06 section": ['id="m6"', 'id="m6_count"'],
    "All readings stats": ['id="x_grid"', "<th>Now</th><th>Min</th><th>Max</th><th>Avg</th><th>Std</th><th>Samples</th>",
                           "function fmtAge", "function fmtRunT", "s.min_t", "s.max_t", "s.age"],
    "Units": ['id="unitsBtn"'],
    "Theme": ['id="themeBtn"'],
    "? help popups": ['id="helpPanel"', "function qbtn", "/api/help"],
    "Codes and lamp": ['id="chipCodes"', 'id="chipLamp"', 'id="a_codes"', 'id="h_codes"'],
    "Guided test": ['data-view="v3"', 'id="go_idle"', 'id="go_rev"', 'id="verdict"'],
    "Upload": ['id="rp_file"'],
    "Transport bar": ['id="rbar"', 'id="rb_restart"', 'id="rb_play"', 'id="rb_speed"', 'id="rb_seek"', 'id="rb_time"', 'id="rb_exit"'],
}


@pytest.mark.parametrize("feature", sorted(RETAINED))
def test_retained_feature_is_still_on_the_page(feature):
    missing = [s for s in RETAINED[feature] if s not in HTML]
    assert not missing, f"{feature}: {missing}"


def test_page_stays_one_file_under_its_size_budget():
    assert len(HTML.encode("utf-8")) < 112_000  # 92,165 bytes before stage 1; raise only on purpose
    assert HTML.count("<script>") == 1 and HTML.count("<style>") == 1
