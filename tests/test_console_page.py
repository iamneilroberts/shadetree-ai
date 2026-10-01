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
    "Skin": ['id="skinBtn"', "shadetree.skin"],
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


# ---- console stage 1: colours live in CSS variables; the Plain palette is today's ------------------
def _css():
    return re.sub(r"/\*.*?\*/", "", re.search(r"<style>(.*?)</style>", HTML, re.S).group(1), flags=re.S)


def _block(selector):
    """The custom properties of the first rule whose selector is exactly `selector`."""
    body = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", _css()).group(1)
    return dict((k, " ".join(v.split())) for k, v in re.findall(r"(--[\w-]+):\s*([^;]+);", body))


PLAIN_DARK = {"--bg": "#0e1113", "--panel": "#171b1f", "--panel2": "#1e2429", "--line": "#2c343b", "--ink": "#e8edf0", "--muted": "#93a0aa",
              "--cyan": "#4fc3e8", "--amber": "#f2a93b", "--ok": "#7fcf94", "--bad": "#f07a5a", "--on-accent": "#06222c", "--banner": "#f2a93b",
              "--msg-bg": "#2a2114", "--banner-ink": "#1a1204"}
PLAIN_LIGHT = {"--bg": "#f3f5f6", "--panel": "#ffffff", "--panel2": "#e9edf0", "--line": "#c9d1d7", "--ink": "#12171a", "--muted": "#4f5c65",
               "--cyan": "#0a7499", "--amber": "#9a5a00", "--ok": "#1d7f3a", "--bad": "#c0361b", "--on-accent": "#ffffff", "--msg-bg": "#fff3dc"}


def test_the_plain_palette_is_todays():
    dark, light = _block(":root"), _block(':root[data-theme="light"]')
    assert {k: dark.get(k) for k in PLAIN_DARK} == PLAIN_DARK
    assert {k: light.get(k) for k in PLAIN_LIGHT} == PLAIN_LIGHT


NEUTRAL = re.compile(r"rgba\((?:0,0,0|255,255,255),[.\d]+\)|#000\b")  # black/white shading in shadows and highlights


def test_colours_live_only_in_the_token_blocks():
    rules = re.sub(r":root(?:\[[^\]]*\])*\s*\{[^}]*\}", "", _css())
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", NEUTRAL.sub("", rules)) == []
    markup = HTML[HTML.index("</style>"):HTML.index("<script>")]
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", " ".join(re.findall(r'style="([^"]*)"', markup))) == []
    js = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)
    js = re.sub(r"\n\s*var PALS = [^\n]*", "", js)  # canvas colours: a canvas cannot read CSS variables
    assert re.findall(r"#[0-9a-fA-F]{6}\b", js) == []


def _lum(hexs):
    c = [int(hexs.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _palette(skin, theme):
    """The general tokens as the cascade gives them for <html data-skin=skin data-theme=theme> (later, more specific blocks win)."""
    sels = [":root"] + ([':root[data-theme="light"]'] if theme == "light" else []) + \
           ([':root[data-skin="retro"]'] if skin == "retro" else []) + \
           ([':root[data-skin="retro"][data-theme="light"]'] if skin == "retro" and theme == "light" else [])
    p = {}
    for s in sels:
        p.update(_block(s))
    return p


TEXT_PAIRS = [("--ink", "--bg"), ("--ink", "--panel"), ("--ink", "--panel2"), ("--muted", "--bg"), ("--muted", "--panel"), ("--muted", "--panel2"),
              ("--cyan", "--panel"), ("--amber", "--panel"), ("--ok", "--panel"), ("--bad", "--panel"), ("--on-accent", "--cyan"),
              ("--amber", "--msg-bg"), ("--banner-ink", "--banner")]


@pytest.mark.parametrize("skin,theme", [("plain", "dark"), ("plain", "light"), ("retro", "dark"), ("retro", "light")])
def test_every_skin_and_theme_keeps_text_readable(skin, theme):  # Review Focus 2
    p = _palette(skin, theme)
    low = [(a, b, round(_contrast(p[a], p[b]), 2)) for a, b in TEXT_PAIRS if _contrast(p[a], p[b]) < 4.5]
    assert low == [], f"{skin}/{theme} text below WCAG AA 4.5:1: {low}"


def test_shared_parts_fit_a_phone_width():  # Review Focus 5
    css = _css()
    rule = lambda sel: re.search(r"(?:^|[}\s])" + re.escape(sel) + r"\s*\{([^}]*)\}", css).group(1)
    tile = int(re.search(r"minmax\((\d+)px", rule(".gauges")).group(1))
    assert 2 * tile + 10 <= 360 - 2 * 16, "two gauges side by side on a 360 px phone inside the 16 px gutters"
    for sel in (".panel", ".panel > .pbody", ".panel > .ptitle .pname", ".gauge", ".gauge .gname"):
        assert "min-width: 0" in rule(sel), sel
    for sel in (".panel > .ptitle .pname", ".gauge .gname"):
        assert "text-overflow: ellipsis" in rule(sel), sel  # a long reading name shortens instead of widening the page
    assert "overflow-x: auto" in rule(".rwrap"), "a wide table scrolls inside its card, not the page"
