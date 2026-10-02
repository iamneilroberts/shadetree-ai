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
    assert {"v0", "v3", "v5", "v6"} <= views
    assert "v4" not in views and 'id="v4"' not in HTML, "the Analyzer view is gone: it is the Retro skin of the Dashboard"
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
    assert re.findall(r'<div class="hh-pane" data-mode="(\w+)"', HTML) == ["live", "codes"]
    for gone in ("h_rpm", "h_l_stft1", "h_status"):
        assert f'id="{gone}"' not in HTML and f"'{gone}'" not in HTML, f"{gone} is gone with the old panes"
    assert re.search(r"\.hh \.gauges \{ grid-template-columns: repeat\(2, 1fr\); \}", HTML), "gauges two across in the Handheld"


def test_phone_width_hides_the_status_and_controls_but_keeps_the_topbar_menu_for_the_handheld_view():
    media = HTML[HTML.index("@media (max-width: 430px)"):]
    assert "100dvh" in media
    hide = re.search(r"([^{}]*)\{ display: none; \}", media).group(1)
    assert "#v5.is-active) .topbar:not(.menu-open) + .status" in hide, "Handheld shows the status and controls once the Menu is open"
    assert not re.search(r"\.topbar(?!:not\(\.menu-open\) \+ \.status)", hide), "the only topbar-related hide is the closed menu's status"
    assert "body:has(#v5.is-active) .banner" in hide and "body:has(#v5.is-active) .msgbar" in hide
    assert re.search(r"body:has\(#v5\.is-active\) \.stage \{ padding: 0; \}", media)
    frame = re.search(r"\.retro \.hh \{([^}]*)\}", media).group(1)
    assert "width: 100%" in frame
    assert re.search(r"height: calc\(100dvh - var\(--topbar-h\)\)", frame), "the frame leaves room for the topbar"
    assert re.search(r"\.topbar \{[^}]*min-height: var\(--topbar-h\)", _css()), "the topbar uses the same height variable"
    assert re.search(r"--topbar-h: \d+px", _css())


def test_phone_menu_collapse_lives_in_the_600px_query_and_uses_no_colour_literals():
    css = _css()
    assert re.search(r"\.menubtn \{[^}]*display: none", css), "no Menu button outside the phone query"
    m = re.search(r"@media \(max-width: 600px\) \{\s*\.topbar \.menubtn \{(.*?)\n  \}", css, re.S)
    assert m, "one 600px block holds the Menu rules"
    block = m.group(0)
    assert "display: inline-block" in block and ":not(.menu-open)" in block and "display: none" in block
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", block)
    narrower = css[css.index("@media (max-width: 430px)"):]
    narrower = narrower[:narrower.index("\n  }") + 4]  # the Handheld phone block is inside the 600px range too
    assert ".menu-open" not in css.replace(block, "").replace(narrower, ""), "nothing collapses above 600px"


# ---- console stage 1: the features every stage must keep (spec "Retained features") ----------------
RETAINED = {
    "Capture all supported": ['id="capAll"', "body.capture = 'all'"],
    "Demo button": ['id="demoBtn"'],
    "Dashboard": ['data-view="v0"', 'id="d_tabs"', 'id="d_table"', 'id="d_edit"'],
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
    "Codes and lamp": ['id="chipCodes"', 'id="chipLamp"', 'id="d_codes_mount"', 'id="h_codes"'],
    "Guided test": ['data-view="v3"', 'id="go_idle"', 'id="go_rev"', 'id="verdict"'],
    "Upload": ['id="rp_file"'],
    "Transport bar": ['id="rbar"', 'id="rb_restart"', 'id="rb_play"', 'id="rb_speed"', 'id="rb_seek"', 'id="rb_time"', 'id="rb_exit"'],
}


@pytest.mark.parametrize("feature", sorted(RETAINED))
def test_retained_feature_is_still_on_the_page(feature):
    missing = [s for s in RETAINED[feature] if s not in HTML]
    assert not missing, f"{feature}: {missing}"


def test_page_stays_one_file_under_its_size_budget():
    assert len(HTML.encode("utf-8")) < 130_000  # 92,165 bytes before stage 1; stage 2 adds the Dashboard and scenarios (about 10 KB) and removes the #vp preview; raise only on purpose
    assert HTML.count("<script>") == 1 and HTML.count("<style>") == 1


# ---- console stage 1: colours live in CSS variables; the Plain palette is today's ------------------
def _css():
    return re.sub(r"/\*.*?\*/", "", re.search(r"<style>(.*?)</style>", HTML, re.S).group(1), flags=re.S)


def _block(selector):
    """The custom properties of the first rule whose selector is exactly `selector`."""
    body = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", _css()).group(1)
    return dict((k, " ".join(v.split())) for k, v in re.findall(r"(--[\w-]+):\s*([^;]+);", body))


def _block_all(selector):
    """The custom properties of every rule whose selector is exactly `selector`, merged in source order."""
    out = {}
    for body in re.findall(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", _css()):
        out.update((k, " ".join(v.split())) for k, v in re.findall(r"(--[\w-]+):\s*([^;]+);", body))
    return out


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
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?)\(", NEUTRAL.sub("", rules)) == []
    markup = HTML[HTML.index("</style>"):HTML.index("<script>")]
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?)\(", " ".join(re.findall(r'style="([^"]*)"', markup))) == []
    js = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)
    js = re.sub(r"\n\s*var PALS = [^\n]*", "", js)  # canvas colours: a canvas cannot read CSS variables
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?)\(", js) == []


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
        p.update(_block_all(s))
    for k in p:  # resolve var(--x) chains (the gauge tokens point at the general and device tokens)
        while (m := re.fullmatch(r"var\((--[\w-]+)\)", p[k])):
            p[k] = p[m.group(1)]
    return p


TEXT_PAIRS = [("--ink", "--bg"), ("--ink", "--panel"), ("--ink", "--panel2"), ("--muted", "--bg"), ("--muted", "--panel"), ("--muted", "--panel2"),
              ("--cyan", "--panel"), ("--amber", "--panel"), ("--ok", "--panel"), ("--bad", "--panel"), ("--on-accent", "--cyan"),
              ("--amber", "--msg-bg"), ("--banner-ink", "--banner"),
              ("--amber", "--panel2"), ("--bad", "--panel2"), ("--g-ink", "--g-face")]  # gauge text: the amber/red notes sit on the gauge card, digits on the face


@pytest.mark.parametrize("skin,theme", [("plain", "dark"), ("plain", "light"), ("retro", "dark"), ("retro", "light")])
def test_every_skin_and_theme_keeps_text_readable(skin, theme):  # Review Focus 2
    p = _palette(skin, theme)
    low = [(a, b, round(_contrast(p[a], p[b]), 2)) for a, b in TEXT_PAIRS if _contrast(p[a], p[b]) < 4.5]
    assert low == [], f"{skin}/{theme} text below WCAG AA 4.5:1: {low}"


def _over(fg, bg):
    """fg composited over the opaque hex bg (the unlit-LED token is a translucent white in Retro)."""
    m = re.fullmatch(r"rgba\((\d+),(\d+),(\d+),([.\d]+)\)", fg.replace(" ", ""))
    if not m:
        return fg
    a, base = float(m[4]), [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(a * int(m[i + 1]) + (1 - a) * base[i]) for i in range(3))


GAUGE_PAIRS = [  # (foreground token, background token, minimum contrast, why, light themes only)
    ("--g-ink", "--g-face", 7.0, "dial text, ticks and arc", False), ("--g-ink2", "--g-face", 4.5, "dial small text", False),
    ("--g-needle", "--g-face", 4.5, "needle", False), ("--g-z-ok", "--g-face", 3.0, "ok zone arc", False),
    ("--g-z-watch", "--g-face", 3.0, "watch zone arc", False), ("--g-z-out", "--g-face", 3.0, "out zone arc", False),
    ("--g-rim", "--g-face", 3.0, "dial rim", True),
    ("--g-ok", "--g-win", 3.0, "lit LED", False), ("--g-warn", "--g-win", 3.0, "lit LED", False), ("--g-bad", "--g-win", 3.0, "lit LED", False),
    ("--g-seg", "--g-win", 3.0, "lit LED", False),
    ("--g-ok", "--g-win", 4.5, "seven-segment digits", False), ("--g-warn", "--g-win", 4.5, "seven-segment digits", False),
    ("--g-bad", "--g-win", 4.5, "seven-segment digits", False), ("--g-seg", "--g-win", 4.5, "seven-segment digits", False),
]


@pytest.mark.parametrize("skin,theme", [("plain", "dark"), ("plain", "light"), ("retro", "dark"), ("retro", "light")])
def test_every_skin_and_theme_keeps_gauge_faces_high_contrast(skin, theme):
    assert _gauge_low(_palette(skin, theme), theme) == [], f"{skin}/{theme} gauge pairs below target"


def _gauge_low(p, theme):
    low = [(a, b, need, why, round(_contrast(p[a], p[b]), 2)) for a, b, need, why, light_only in GAUGE_PAIRS
           if (theme == "light" or not light_only) and _contrast(p[a], p[b]) < need]
    off = _over(p["--g-led-off"], p["--g-win"])
    low += [(a, "unlit LED", 2.0, "lit vs unlit", round(_contrast(p[a], off), 2)) for a in ("--g-ok", "--g-warn", "--g-bad", "--g-seg")
            if _contrast(p[a], off) < 2.0]
    return low


@pytest.mark.parametrize("skin,theme", [("plain", "dark"), ("plain", "light"), ("retro", "dark"), ("retro", "light")])
def test_the_always_retro_handheld_keeps_gauge_faces_high_contrast_in_every_skin_and_theme(skin, theme):
    p = _palette(skin, theme)
    p.update(_block_all(".retro"))  # the .retro wrapper's overrides win inside it, over whichever skin and theme the page wears
    for k in p:
        while (m := re.fullmatch(r"var\((--[\w-]+)\)", p[k])):
            p[k] = p[m.group(1)]
    low = _gauge_low(p, theme)
    assert low == [], f"Handheld under {skin}/{theme}: gauge pairs below target: {low}"


def test_shared_parts_fit_a_phone_width():  # Review Focus 5
    css = _css()
    rule = lambda sel: re.search(r"(?:^|\})\s*" + re.escape(sel) + r"\s*\{([^}]*)\}", css).group(1)  # the base rule: the selector starts the rule, so `.hh .gauges` is not read as `.gauges`
    tile = int(re.search(r"minmax\((\d+)px", rule(".gauges")).group(1))
    assert 2 * tile + 10 <= 360 - 2 * 16, "two gauges side by side on a 360 px phone inside the 16 px gutters"
    for sel in (".panel", ".panel > .pbody", ".panel > .ptitle .pname", ".gauge", ".gauge .gname"):
        assert "min-width: 0" in rule(sel), sel
    for sel in (".panel > .ptitle .pname", ".gauge .gname"):
        assert "text-overflow: ellipsis" in rule(sel), sel  # a long reading name shortens instead of widening the page
    assert "overflow-x: auto" in rule(".rwrap"), "a wide table scrolls inside its card, not the page"


def test_dashboard_code_list_scrolls_instead_of_clipping_and_its_small_text_is_readable():
    rules = re.findall(r"(?m)^\s*#v0 \.clist\s*\{([^}]*)\}", HTML)
    assert rules, "a #v0-only .clist rule must exist"
    body = rules[-1]
    assert "overflow-y: auto" in body and "overflow: hidden" not in body
    assert "176px" not in body.replace("min-height: 176px", "") and "height: auto" in body
    assert re.search(r"(?m)^\s*#v0 \.cfoot, #v0 \.cntbox small \{\s*color: var\(--muted\)", HTML)


def _css_rules(css, media=None):
    """(media condition or None, selector list, body) for every style rule; one level of @media is walked."""
    out, i = [], 0
    while i < len(css):
        j = css.find("{", i)
        if j < 0:
            break
        head, depth, k = css[i:j].strip(), 1, j + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        body = css[j + 1:k - 1]
        if head.startswith("@media"):
            out += _css_rules(body, head[len("@media"):].strip())
        elif not head.startswith("@"):
            out.append((media, [s.strip() for s in head.split(",")], body))
        i = k
    return out


def _cabinet_rules(css):
    return [r for r in _css_rules(css) if any(".dcab" in s or ".dface" in s for s in r[1])]


def test_cabinet_chrome_is_retro_desktop_only():
    rules = _cabinet_rules(_css())
    assert rules, "the Dashboard cabinet has CSS"
    assert 'class="dcab"' in HTML and "dcab retro" not in HTML and "retro dcab" not in HTML, "the wrapper never wears the .retro class (it restyles Plain)"
    assert HTML.count('id="clarity"') == 1, "one Clarity button on the page"
    assert re.search(r'<div class="dcab"><div class="dface">', HTML) and 'class="plate"' in HTML[HTML.index('class="dcab"'):HTML.index('id="v5"')]
    for media, sels, body in rules:
        flat = " ".join(body.split())
        if media is None and not all(s.startswith(':root[data-skin="retro"]') for s in sels):
            # unscoped base: only hides the decorative chrome, never gives the wrapper or the face a look
            assert flat in ("display: none;", "display: none"), f"{sels} outside the Retro skin may only be display: none"
            assert all(re.search(r"\.dcab \.(plate|screw|bench)$", s) for s in sels), f"{sels}: only plate, screw and bench are hidden unscoped"
        else:
            assert media == "(min-width: 601px)", f"{sels} gives the cabinet a look outside the desktop media query: {media}"
            assert all(s.startswith(':root[data-skin="retro"] ') for s in sels), f"{sels} is not scoped to the Retro skin"
    scoped = " ".join(" ".join(r[1]) for r in rules if r[0])
    for needle in (".dcab::before", ".dcab::after", ".dface", ".dface > .plate", ".screw", ".bench", ".rocker", ".dcab.max"):
        assert needle in scoped, f"Retro desktop rule for {needle}"
    hidden = " ".join(" ".join(r[1]) for r in rules if not r[0])
    for needle in (".dcab .plate", ".dcab .screw", ".dcab .bench"):
        assert needle in hidden, f"{needle} is hidden by default"


FACE_OVERRIDES = {  # what sits directly on the light cabinet face (not inside its own panel/card) and so needs a face-safe colour
    "h3.sec": "text", "#o_note": "text", "#d_table > .note": "text", ".more": "text", "table.rd th": "text", "table.rd td .at": "text", ".dash": "text",
    "tr.scen td:first-child": "marker",
}


def _face_override(css, frag):
    for media, sels, body in _cabinet_rules(css):
        if media == "(min-width: 601px)" and any(s.endswith(frag) and s.startswith(':root[data-skin="retro"] #v0 .dface ') for s in sels):
            m = re.search(r"(?:color:|box-shadow: inset 3px 0 0)\s*var\((--[\w-]+)\)", body)
            if m:
                return m.group(1)
    return None


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_text_and_marker_directly_on_the_light_cabinet_face_are_readable(theme):
    p, css = _palette("retro", theme), _css()
    face = re.findall(r"#[0-9a-fA-F]{6}", p["--face"])
    assert len(face) == 2
    for frag, kind in FACE_OVERRIDES.items():
        tok = _face_override(css, frag)
        assert tok, f"{frag}: a Retro desktop override gives it a face-safe colour"
        need = 4.5 if kind == "text" else 3.0
        assert all(_contrast(p[tok], f) >= need for f in face), f"{frag}: {tok} {p[tok]} on the face is below {need}:1"
    if theme == "dark":
        assert any(_contrast(p["--muted"], f) < 4.5 for f in face), "sanity: the page's --muted is unreadable on the face in Retro dark"
    assert not any(s.endswith(".dface .note") for _, ss, _ in _cabinet_rules(css) for s in ss), "a blanket .dface .note would darken notes inside the dark panels"


# ---- console stage 3: the replay bar is pinned to the bottom on a phone -----------------------------
def _rbar_problems(css):
    """Everything wrong with the phone replay-bar rules in `css` (empty when they hold)."""
    rules = _css_rules(css)
    p600 = [r for r in rules if r[0] == "(max-width: 600px)"]
    p430 = [r for r in rules if r[0] == "(max-width: 430px)"]
    shown = ".rbar:not([hidden])"
    bad = []
    fixed = [b for _, sels, b in p600 if shown in sels]
    if not fixed or not all(re.search(p, " ".join(fixed[0].split())) for p in
                            (r"position: fixed;", r"(?<![-\w])bottom: 0;", r"(?<![-\w])left: 0;", r"(?<![-\w])right: 0;", r"z-index: \d+;", r"border-top: [^;]*var\(--line\)", r"background: var\(--panel2\)")):
        bad.append("the shown bar is not fixed to the bottom edge with a token background and top border inside the 600px block")
    if any(re.search(r"position:\s*fixed", b) for m, s, b in rules if m != "(max-width: 600px)" and any(".rbar" in x for x in s)):
        bad.append("the bar is fixed outside the 600px block")
    if len(re.findall(r"--rbar-h:\s*88px", css)) != 1 or not any(re.search(r"--rbar-h:\s*88px", b) for m, s, b in rules if m in (None, "(max-width: 600px)")):
        bad.append("--rbar-h is not defined exactly once as 88px")
    stage = [b for _, sels, b in p600 if "body:has(.rbar:not([hidden])) .stage" in sels]
    if not stage or "padding-bottom: var(--rbar-h)" not in stage[0]:
        bad.append("the stage does not reserve --rbar-h while the bar is shown")
    hh = [b for _, sels, b in p430 if "body:has(.rbar:not([hidden])) .hh" in sels]
    if not hh or "height: calc(100dvh - var(--topbar-h) - var(--rbar-h))" not in hh[0]:
        bad.append("the Handheld frame does not end above the bar while it is shown")
    if re.search(r"88px", "".join(b for m, s, b in rules if any("rbar" in x for x in s) and "--rbar-h:" not in b)):
        bad.append("a rule hard-codes the bar height")
    mine = "".join(b for _, s, b in rules if any("rbar" in x for x in s))
    if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", mine):
        bad.append("a colour literal in the bar rules")
    return bad


def test_replay_bar_is_pinned_to_the_bottom_on_a_phone_with_room_reserved():
    assert _rbar_problems(_css()) == []
