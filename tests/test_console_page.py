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


def test_phone_handheld_has_one_scroller_and_keeps_the_footer_caveat_inside_the_frame():
    media = HTML[HTML.index("@media (max-width: 430px)"):]
    hide = re.search(r"([^{}]*)\{ display: none; \}", media).group(1)
    assert "body:has(#v5.is-active) .foot" in hide, "the page footer under the full-height frame made the page scroll as well as the frame"
    assert re.search(r"\.retro \.hh-foot \{ display: none; \}", HTML) and re.search(r"\.retro \.hh-foot \{ display: block; \}", media)
    pane = HTML[HTML.index('id="h_livepane"'):HTML.index('id="h_codes"')]
    assert "rules of thumb, not limits for your car [general knowledge, unverified]" in pane


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
    "Capture level (was Capture all supported)": ['id="capLvl"', 'id="cap_min"', 'id="cap_std"', 'id="cap_max"', "body.capture = lv"],
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
    assert len(HTML.encode("utf-8")) < 260_000  # 92,165 bytes before stage 1; stage 2 adds the Dashboard and scenarios (about 10 KB) and removes the #vp preview; raised to 150,000 on 2026-10-02 (Neil) for the UI polish pass; raised to 260,000 for embedded fonts and the 1970s cabinet skin, 2026-10-02, Neil; raise only on purpose
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
    """The general tokens as the cascade gives them for <html data-skin=skin data-theme=theme> (later, more specific blocks win).
    skin "retro-dashboard" is Retro with the Dashboard showing (data-view="v0"): its gunmetal page around the cabinet."""
    dash, skin = skin == "retro-dashboard", "retro" if skin == "retro-dashboard" else skin
    sels = [":root"] + ([':root[data-theme="light"]'] if theme == "light" else []) + \
           ([':root[data-skin="retro"]'] if skin == "retro" else []) + \
           ([':root[data-skin="retro"][data-theme="light"]'] if skin == "retro" and theme == "light" else []) + \
           ([':root[data-skin="retro"][data-view="v0"]'] if dash else [])
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


@pytest.mark.parametrize("skin,theme", [("plain", "dark"), ("plain", "light"), ("retro", "dark"), ("retro", "light"), ("retro-dashboard", "dark"), ("retro-dashboard", "light")])
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
    assert len(rules) == 1, "one #v0-only .clist rule"
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


def test_dashboard_code_rows_give_the_description_its_own_row_on_a_phone():
    p600 = [(s, b) for m, s, b in _css_rules(_css()) if m == "(max-width: 600px)"]
    row = [b for s, b in p600 if "#v0 .crow" in s]
    assert row and "grid-template-columns: auto 1fr" in row[0], "code and status share a row, sized to their content"
    assert any("#v0 .crow .cdesc" in s and "grid-column: 1 / -1" in b for s, b in p600), "the description spans the whole row"


def test_handheld_alert_repeats_the_notices_inside_the_frame_using_tokens_only():
    assert re.search(r'<div class="hh-scen">.*?</div>\s*<div class="hh-alert" id="h_alert" hidden></div>\s*<div class="hh-body">', HTML, re.S)
    rules = [(m, b) for m, s, b in _css_rules(_css()) if ".retro .hh-alert" in s]
    assert rules and all("var(--msg-bg)" in b or "var(--amber)" in b or "display" in b for m, b in rules)
    assert any(m == "(max-width: 430px)" and "display: block" in b for m, b in rules), "shown only where the page hides its own notices"
    body = " ".join(b for m, b in rules)
    assert "background: var(--msg-bg)" in body and "color: var(--amber)" in body  # the --amber on --msg-bg pair is held by TEXT_PAIRS


_CAB_MEDIA = (None, "(max-width: 900px)", "(max-width: 600px)", "(max-width: 360px)", "(min-width: 701px)", "(min-width: 701px) and (prefers-reduced-motion: reduce)")  # the Retro cabinet at every width (changed 2026-10-02: it was desktop only); the knob above 700 px


def _cabinet_rules(css):
    return [r for r in _css_rules(css) if any(".dcab" in s or ".dface" in s for s in r[1])]


def test_cabinet_chrome_is_retro_only_at_every_width():
    rules = _cabinet_rules(_css())
    assert rules, "the Dashboard cabinet has CSS"
    assert 'class="dcab"' in HTML and "dcab retro" not in HTML and "retro dcab" not in HTML, "the wrapper never wears the .retro class (it restyles Plain)"
    assert HTML.count('id="clarity"') == 1, "one Clarity button on the page"
    assert re.search(r'<div class="dcab"><div class="dface">', HTML) and 'class="plate"' in HTML[HTML.index('class="dcab"'):HTML.index('id="v5"')]
    for media, sels, body in rules:
        flat = " ".join(body.split())
        if not all(s.startswith(':root[data-skin="retro"]') for s in sels):
            # unscoped base: only hides the decorative chrome, never gives the wrapper or the face a look
            assert flat in ("display: none;", "display: none"), f"{sels} outside the Retro skin may only be display: none"
            assert media is None and all(re.search(r"\.dcab \.(plate|screw|knob)$", s) for s in sels), f"{sels}: only plate, screw and knob are hidden unscoped"
        else:
            assert media in _CAB_MEDIA, f"{sels} gives the cabinet a look in an unexpected media query: {media}"
    scoped = " ".join(" ".join(r[1]) for r in rules if all(s.startswith(':root[data-skin="retro"]') for s in r[1]))
    for needle in (".dcab::before", ".dcab::after", ".dface", ".dface > .plate", ".screw", ".dcab.max"):   # the Display bench and its rocker are gone: Clarity is in the Options drawer (2026-10-02)
        assert needle in scoped, f"Retro rule for {needle}"
    hidden = " ".join(" ".join(r[1]) for r in rules if not all(s.startswith(':root[data-skin="retro"]') for s in r[1]))
    for needle in (".dcab .plate", ".dcab .screw", ".dcab .knob"):
        assert needle in hidden, f"{needle} is hidden by default"


def _steel(p):
    """The cabinet body's colours, top to bottom: the hammertone steel gradient's stops (Retro, desktop)."""
    return [p["--cb-steel-hi"], p["--cb-steel"], p["--cb-steel-lo"]]


FACE_OVERRIDES = {  # what sits directly on the cabinet's steel body (not inside its own panel/card) and so needs a steel-safe colour
    "h3.sec": "text", "#o_note": "text", "#d_table > .note": "text", ".more": "text", "table.rd th": "text", "table.rd td .at": "text",
}  # the readings table itself is the CRT bay (black): test_retro_readings_table_is_the_crt_bay


def _face_override(css, frag):
    for media, sels, body in _cabinet_rules(css):
        if media is None and any(s.endswith(frag) and s.startswith(':root[data-skin="retro"] #v0 .dface ') for s in sels):
            m = re.search(r"(?:color:|box-shadow: inset 3px 0 0)\s*var\((--[\w-]+)\)", body)
            if m:
                return m.group(1)
    return None


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_text_and_marker_directly_on_the_cabinet_steel_are_readable(theme):
    p, css = _palette("retro", theme), _css()
    face = _steel(p)
    for frag, kind in FACE_OVERRIDES.items():
        tok = _face_override(css, frag)
        assert tok, f"{frag}: a Retro desktop override gives it a steel-safe colour"
        need = 4.5 if kind == "text" else 3.0
        assert all(_contrast(p[tok], f) >= need for f in face), f"{frag}: {tok} {p[tok]} on the face is below {need}:1"
    if theme == "dark":
        assert any(_contrast(p["--meter-ink2"], f) < 4.5 for f in face), "sanity: the old light-face ink is unreadable on the dark steel"
    assert not any(s.endswith(".dface .note") for _, ss, _ in _cabinet_rules(css) for s in ss), "a blanket .dface .note would darken notes inside the dark panels"


def test_every_pid_table_row_has_the_same_left_bar_and_scenario_rows_only_recolour_it():
    rules = _css_rules(_css())
    base = [b for m, s, b in rules if m is None and "table.rd tbody td:first-child" in s]
    assert base and "box-shadow: inset 3px 0 0 var(--line)" in base[0], "every row of every PID table gets a 3px neutral left bar, so the edge is even"
    scen = [(m, s, b) for m, s, b in rules if any("tr.scen" in x for x in s)]
    assert len(scen) >= 2, "the plain marker and the Retro cabinet marker"
    for m, s, b in scen:
        decl = [d.strip() for d in b.split(";") if d.strip()]
        assert len(decl) == 1 and re.fullmatch(r"box-shadow: inset 3px 0 0 var\(--[\w-]+\)", decl[0]) and "--line" not in decl[0], f"{s}: .scen only recolours the bar"


_R = ':root[data-skin="retro"] '


def _spec(sel):
    """CSS specificity (ids, classes/attributes/pseudo-classes, elements) for the simple selectors used here."""
    return (len(re.findall(r"#[\w-]+", sel)), len(re.findall(r"\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+", sel)),
            len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", sel)))


def _bar_tok(rules, skin, media_ok, candidates):
    """The left-bar colour token the winning rule (highest specificity, then the later one) gives among `candidates`."""
    best = None
    for i, (media, sels, body) in enumerate(rules):
        if media not in media_ok:
            continue
        for s in sels:
            if s in candidates and (skin == "retro" or not s.startswith(_R)):
                m = re.search(r"box-shadow: inset 3px 0 0 var\((--[\w-]+)\)", body)
                if m and (best is None or (_spec(s), i) >= best[0]):
                    best = ((_spec(s), i), m.group(1))
    return best and best[1]


_BAR = "table.rd tbody td:first-child"
_BAR_CONTEXTS = [  # (where, skins, media, a plain row's candidate selectors, a scenario row's extra selectors or None, background)
    ("Dashboard readings in the CRT bay (Retro, any width)", {"retro"}, {None, "(min-width: 601px)"}, [_BAR, _R + "#v0 .dface " + _BAR, _R + "#d_table.crt " + _BAR],
     ["#d_table tr.scen td:first-child", _R + "#d_table.crt table.rd tbody tr.scen td:first-child"], "--cb-face"),
    ("Dashboard on the page (Plain)", {"plain"}, {None}, [_BAR], ["#d_table tr.scen td:first-child"], "--bg"),
    ("Handheld table on the device face", {"plain", "retro"}, {None, "(min-width: 601px)"}, [_BAR, ".retro .hh " + _BAR], None, "face"),
]


@pytest.mark.parametrize("skin,theme", [("plain", "dark"), ("plain", "light"), ("retro", "dark"), ("retro", "light")])
def test_the_neutral_row_bar_is_fainter_than_the_scenario_marker_on_every_surface(skin, theme):
    rules, p = _css_rules(_css()), _palette(skin, theme)
    face = re.findall(r"#[0-9a-fA-F]{6}", p["--face"])
    bad = []
    for where, skins, media, plain, scen, back in _BAR_CONTEXTS:
        if skin not in skins:
            continue
        backs = face if back == "face" else _steel(p) if back == "steel" else [p[back]]
        neutral = _bar_tok(rules, skin, media, plain)
        marker = _bar_tok(rules, skin, media, plain + scen) if scen else "--meter-zone"  # the Handheld has no scenario rows: the cabinet marker on the same face is the reference
        assert neutral and marker and neutral != marker, f"{where}: neutral {neutral}, marker {marker}"
        for b in backs:
            n, m = _contrast(p[neutral], b), _contrast(p[marker], b)
            if not (1.2 <= n < m):
                bad.append((where, neutral, round(n, 2), marker, round(m, 2), b))
    assert bad == [], f"{skin}/{theme}: the neutral bar must be visible (>= 1.2:1) and fainter than the scenario marker: {bad}"


# ---- feedback wave: text inside the Retro cabinet and the Handheld is readable on its own card --------
_CAB = [["body"], [_R + "#v0 .dface"]]  # the Dashboard: page ink, then the cabinet body's engraving ink (Retro, every width)
_HH = [["body"], [".retro"], [".retro .hh-in"]]  # the Handheld: page ink, the device ink, the light face's ink
_DGAUGE, _HGAUGE = [[".gauge"]], [[".gauge", ".retro .hh .gauge"]]  # a gauge card on the Dashboard, and in the Handheld


def _decl_tok(rules, sel, skin, prop):
    """The token in the last `prop: var(--x)` of a rule listing exactly `sel` (desktop width); Retro-scoped rules only in Retro."""
    if skin != "retro" and sel.startswith(_R):
        return None
    tok = None
    for media, sels, body in rules:
        if media in (None, "(min-width: 601px)") and sel in sels:
            for m in re.finditer(r"(?<![-\w])" + prop + r":\s*var\((--[\w-]+)\)", body):
                tok = m.group(1)
    return tok


def _effective_ink(rules, skin, chain):
    """The inherited text colour: the innermost element of `chain` (outer to inner, each a list of its selectors in rising precedence) that sets one."""
    for element in reversed(chain):
        for sel in reversed(element):
            if tok := _decl_tok(rules, sel, skin, "color"):
                return tok
    return None


_INK_CASES = [  # (where, chain, background: selectors inner to outer whose background is the card, or "face")
    ("Dashboard gauge value", _CAB + [[".panel"]] + _DGAUGE + [[".gauge .gval"]], [".gauge"]),
    ("Dashboard gauge name", _CAB + [[".panel"]] + _DGAUGE + [[".gauge .gtop"], [".gauge .gname"]], [".gauge"]),
    ("Dashboard gauge note", _CAB + [[".panel"]] + _DGAUGE + [[".gauge .gnote"]], [".gauge"]),
    ("Dashboard gauge watch note", _CAB + [[".panel"]] + _DGAUGE + [[".gauge .gnote", ".gauge.watch .gnote"]], [".gauge"]),
    ("Dashboard gauge out note", _CAB + [[".panel"]] + _DGAUGE + [[".gauge .gnote", ".gauge.out .gnote"]], [".gauge"]),
    ("Handheld gauge value", _HH + _HGAUGE + [[".gauge .gval"]], [".gauge"]),
    ("Handheld gauge name", _HH + _HGAUGE + [[".gauge .gtop"], [".gauge .gname"]], [".gauge"]),
    ("Handheld gauge note", _HH + _HGAUGE + [[".gauge .gnote"]], [".gauge"]),
    # the rest of the cabinet, by the same method
    ("panel title", _CAB + [[".panel"], [".panel > .ptitle"]], [".panel > .ptitle", ".panel"]),
    ("panel note (no gauges)", _CAB + [[".panel"], ["#v0 .note"]], [".panel"]),
    ("gauge editor row", _CAB + [[".panel"], [".edbox"], [".edrow span"]], [".panel"]),
    ("scenario tab", _CAB + [[".stab"]], [".stab"]), ("active scenario tab", _CAB + [[".stab", ".stab.is-active"]], [".stab.is-active"]),
    ("edit pencil", _CAB + [[".qbtn"]], [".qbtn"]),
    ("lamp", _CAB + [["#v0 .lampbox"]], ["#v0 .lampbox"]), ("lit lamp", _CAB + [["#v0 .lampbox", "#v0 .lampbox.lit"]], ["#v0 .lampbox"]),
    ("codes count caption", _CAB + [[".panel"], ["#v0 .cntbox small"]], [".panel"]),
    ("codes footnote", _CAB + [[".panel"], ["#v0 .cfoot"]], [".panel"]),
    ("code description", _CAB + [[".panel"], ["#v0 .clist"], ["#v0 .cdesc"]], ["#v0 .clist"]),
    ("code hint", _CAB + [[".panel"], ["#v0 .clist"], ["#v0 .chint"]], ["#v0 .clist"]),
    ("health tile value", _CAB + [["#v0 .tile"], [".big"]], ["#v0 .tile"]),
    ("health tile title", _CAB + [["#v0 .tile"], ["h3", "#v0 .tile h3"]], ["#v0 .tile"]),
    ("health tile unit", _CAB + [["#v0 .tile"], [".unit"]], ["#v0 .tile"]),
    ("health tile subtitle", _CAB + [["#v0 .tile"], ["#v0 .tile .sub"]], ["#v0 .tile"]),
    ("attention name", _CAB + [["#v0 .attn"], ["#v0 .orow"], ["#v0 .orow .nm"]], ["#v0 .attn"]),
    ("attention value", _CAB + [["#v0 .attn"], ["#v0 .orow"], ["#v0 .orow .val"]], ["#v0 .attn"]),
    ("attention reason", _CAB + [["#v0 .attn"], ["#v0 .orow"], ["#v0 .orow .why"]], ["#v0 .attn"]),
    ("help button", _CAB + [[".q"]], [".q"]),
    ("Dashboard table cell", _CAB + [["table.rd td", _R + "#d_table.crt table.rd td"]], "crt"),
    ("Dashboard table name", _CAB + [["table.rd td", _R + "#d_table.crt table.rd td"], [_R + "#d_table.crt table.rd td.n"]], "crt"),
    ("Dashboard table head", _CAB + [["table.rd th", _R + "#v0 .dface table.rd th", _R + "#d_table.crt table.rd th"]], "crt"),
    ("Dashboard table when", _CAB + [["table.rd td"], ["table.rd td .at", _R + "#v0 .dface table.rd td .at", _R + "#d_table.crt table.rd td .at"]], "crt"),
    ("Health heading", _CAB + [["h3", "#v0 h3.sec", _R + "#v0 .dface h3.sec"]], "face"),
    ("Handheld table cell", _HH + [["table.rd td"]], "hhface"),
    ("Handheld table head", _HH + [["table.rd th", ".retro .hh table.rd th"]], "hhface"),
    ("Handheld All readings button", _HH + [[".retro .hh-tbl"]], [".retro .hh-tbl"]),
]


@pytest.mark.parametrize("skin,theme", [("plain", "dark"), ("plain", "light"), ("retro", "dark"), ("retro", "light")])
def test_text_in_the_cabinet_and_the_handheld_reads_on_its_own_card(skin, theme):
    rules, p = _css_rules(_css()), _palette(skin, theme)
    p.update(_block_all(".retro"))  # the device tokens (only the gauge-face ones differ inside .retro, and gauge faces are not text here)
    for k in p:
        while (m := re.fullmatch(r"var\((--[\w-]+)\)", p[k])):
            p[k] = p[m.group(1)]
    face = re.findall(r"#[0-9a-fA-F]{6}", p["--face"])
    cab = dict(p)  # inside the Retro cabinet body the page tokens point at the engraving colours
    if skin == "retro":
        cab.update(_block_all(_R + "#v0 .dface"))
        for k in cab:
            while (m := re.fullmatch(r"var\((--[\w-]+)\)", cab[k])):
                cab[k] = cab[m.group(1)]
    low = []
    for where, chain, bg in _INK_CASES:
        q = cab if chain[:2] == _CAB else p
        ink = _effective_ink(rules, skin, chain)
        assert ink, f"{where}: no text colour anywhere in its chain"
        if bg == "hhface":
            backs = face  # the light device face (its two gradient stops)
        elif bg == "face" and skin == "retro":
            backs = _steel(p)  # the cabinet's steel body
        elif bg == "crt" and skin == "retro":
            backs = [p["--cb-face"]]  # the readings table's black screen
        elif bg in ("face", "crt"):
            backs = [p["--bg"]]  # Plain has no cabinet: the page
        else:
            backs = [q[t] for t in (_decl_tok(rules, s, skin, "background") for s in bg) if t and re.fullmatch(r"#[0-9a-fA-F]{6}", q[t])][:1]
        assert backs, f"{where}: no opaque background found in {bg}"
        low += [(where, ink, q[ink], b, round(_contrast(q[ink], b), 2)) for b in backs if _contrast(q[ink], b) < 4.5]
    assert low == [], f"{skin}/{theme}: text below 4.5:1 on its card: {low}"
    assert _decl_tok(rules, ".gauge", skin, "color"), "the gauge card sets its own text colour, so it reads in any container"


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


def test_touch_controls_are_44px_and_the_topbar_height_follows_the_menu_button():
    css = _css()
    touch = css[css.index("@media (max-width: 600px), (pointer: coarse) {"):]
    touch = touch[:touch.index("\n  }")]
    sels = re.search(r"([^{}]*)\{ min-height: 44px; \}", touch).group(1)
    assert {s.strip() for s in sels.split(",")} >= {"button.b", "select.b", ".vbtn", ".stab", ".qbtn", "label.chip"}
    assert re.search(r"\.q::after \{ content: \"\"; position: absolute; inset: calc\(50% - 22px\); \}", touch), "a ? keeps its size with a 44px hit area"
    assert re.search(r"\.topbar \.menubtn \{[^}]*min-height: 44px", css) and re.search(r"\.retro \.hh-tbl \{[^}]*min-height: 44px", css)
    assert int(re.search(r"--topbar-h: (\d+)px", css).group(1)) == 44 + 12 + 1, "the phone topbar (6px padding each side, 1px border) fits the Menu button exactly, so the Handheld frame does not overflow"


def test_open_menu_leaves_room_to_scroll_the_handheld_nav_above_the_replay_bar():
    narrower = _css()[_css().index("@media (max-width: 430px)"):]
    assert re.search(r"body:has\(#v5\.is-active\):has\(\.topbar\.menu-open\):has\(\.rbar:not\(\[hidden\]\)\) \.stage \{ padding-bottom: var\(--rbar-h\); \}", narrower[:narrower.index("\n  }")])


# ---- 1970s shop-cabinet port (2026-10-02): plate, fonts, black meter faces, CRT table, test selector ----
def test_cabinet_plate_reads_shadetree_model_br_549():
    cab = HTML[HTML.index('class="dcab"'):HTML.index('id="v5"')]
    plate = re.search(r'<div class="plate">(.*?)</div></div>', cab, re.S).group(1)
    assert "<b>SHADETREE</b>" in plate and "Model BR-549 &middot; Engine Analyzer" in plate and "SER. 0709" in plate
    assert "7-A" not in HTML, "the old model number is gone everywhere on the page"


def test_cabinet_fonts_are_embedded_data_uris_and_the_stencil_set_uses_them():
    faces = re.findall(r'@font-face \{ font-family: "([^"]+)"; font-style: normal; font-weight: ([\d ]+); src: url\(data:font/woff2;base64,[A-Za-z0-9+/=]{2000,}\) format\("woff2"\); \}', HTML)
    assert sorted(faces) == [("Archivo Narrow", "400 700"), ("Cabinet Mono", "400"), ("Cabinet Stencil", "400"), ("Cabinet Stencil", "700")]
    assert HTML.count("@font-face") == 4, "only the weights the cabinet uses"
    root = _block_all(":root")
    assert root["--cb-stencil"].startswith('"Cabinet Stencil"') and root["--cb-label"].startswith('"Archivo Narrow"') and root["--cb-mono"].startswith('"Cabinet Mono"')
    cab = [(s, b) for m, ss, b in _cabinet_rules(_css()) if m is None for s in ss]
    uses = lambda frag, tok: any(s.endswith(frag) and "var(" + tok + ")" in b for s, b in cab)
    assert uses("#v0 .dface", "--cb-label"), "labels and body text in Archivo Narrow"
    assert uses(".plate .np b", "--cb-stencil") and uses(".panel > .ptitle", "--cb-stencil") and uses("#v0 .dface h3.sec", "--cb-stencil"), "plate and legends in the stencil"
    assert "SIL OFL 1.1" in HTML[:HTML.index(":root {")] and resources.files("obd_reader.web").joinpath("FONTS-OFL.txt").is_file()


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_retro_dashboard_indicators_sit_on_pure_black_in_both_themes(theme):
    p = _palette("retro", theme)
    assert _block_all(":root")["--cb-face"] == "#000000"
    assert p["--g-face"] == "#000000" and p["--g-win"] == "#000000", "dials, LED bar tracks and seven-segment windows are black"
    css = _css()
    bezel = [b for m, ss, b in _cabinet_rules(css) if m is None and any(s.endswith("#v0 .dface .gauge .gface") for s in ss)]
    assert bezel and "linear-gradient(var(--cb-face), var(--cb-face)) padding-box" in bezel[0], "the face inside every bezel is black"
    assert any(any(s.endswith("#v0 .dface .win") for s in ss) and "background: var(--cb-face)" in b for m, ss, b in _cabinet_rules(css)), "the code-count window too"
    hh = dict(p); hh.update(_block_all(".retro")); hh.update(_block_all(':root[data-skin="retro"] .stage-pad.retro'))
    assert hh["--g-face"] == "var(--meter-face)" and hh["--g-win"] == "var(--win-bg)", "the Handheld keeps its own faces and windows"


def test_retro_readings_table_is_the_crt_bay():
    assert '<div id="d_table" class="crt"></div>' in HTML, "the Dashboard table carries the scheme class"
    rules, css = _css_rules(_css()), _css()
    crt = [(m, ss, b) for m, ss, b in rules if any(s.startswith(_R + "#d_table.crt") for s in ss)]
    assert crt and all(m in (None, "(max-width: 600px)") for m, _, _ in crt), "the scheme applies at every width, Retro only"
    frame = [b for m, ss, b in crt if _R + "#d_table.crt .rwrap" in ss and m is None][0]
    assert "background: var(--cb-face)" in frame and "border: 9px solid var(--cb-trim)" in frame
    for theme in ("dark", "light"):
        p = _palette("retro", theme)
        for fg, need in (("--crt-fg", 7.0), ("--crt-head-fg", 7.0), ("--crt-muted", 4.5)):
            assert _contrast(p[fg], p["--cb-face"]) >= need, (theme, fg)
        assert 1.2 <= _contrast(p["--crt-rule"], p["--cb-face"]) < _contrast(p["--crt-rule-strong"], p["--cb-face"]) < _contrast(p["--cb-needle"], p["--cb-face"]), "rules faint, row bar visible, scenario marker strongest"
    assert any(any(s.endswith("#d_table.crt table.rd .dash") for s in ss) and "var(--crt-muted)" in b for m, ss, b in crt)


def test_rotary_selector_shows_only_on_a_wide_retro_desktop_and_falls_back_to_the_pushbuttons():
    assert re.search(r'<button class="qbtn" id="d_edit"[^>]*>&#9998;</button>\s*<div class="knob" id="d_knob"></div>', HTML), "the knob sits in the scenario bar"
    rules = _cabinet_rules(_css())
    show = [(m, ss, b) for m, ss, b in rules if any(s.endswith(" .knob") for s in ss) and "display: block" in b]
    hide_tabs = [(m, ss, b) for m, ss, b in rules if any(s.endswith(" .stabs") for s in ss) and "display: none" in b]
    for found in (show, hide_tabs):
        assert len(found) == 1 and found[0][0] == "(min-width: 701px)", "only wider than 700 px; at 700 px or less the tabs stay, styled as pushbuttons"
        sel = found[0][1][0]
        assert ':has(.knob[data-on="1"])' in sel and ':not(:has(#d_edit[aria-pressed="true"]))' in sel, "never while editing, never with too many scenarios"
    js = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)
    assert "role=\"radiogroup\" aria-label=\"Scenario\"" in js and "role=\"radio\" aria-checked=" in js
    for k in ("ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "Home", "End"):
        assert "'" + k + "'" in js, k
    push = [b for m, ss, b in rules if any(s.endswith("#v0 .dface .stab") for s in ss)]
    assert push and "border: 4px solid transparent" in push[0] and "var(--cb-cap-1)" in push[0], "the fallback tabs are chrome-bezelled pushbuttons"


def test_the_cabinet_has_a_phone_layout_and_the_knob_stays_desktop_only():
    rules = _cabinet_rules(_css())
    phone = {s: " ".join(b.split()) for m, ss, b in rules if m == "(max-width: 600px)" for s in ss}
    P = _R + "#v0 .dface"
    assert phone[_R + ".dcab"] == "padding: 0 5px;", "thin end cheeks on a phone"
    assert "width: 5px" in phone[_R + ".dcab::before"]
    assert phone[P + "::before"] == "display: none;" and P + "::after" in phone, "no handle or kick plate on a phone"
    assert "repeat(2, minmax(0, 1fr))" in phone[P + " .gauges"], "gauges two across"
    assert '"top" "face" "val" "note"' in phone[P + " .gauge"], "the reading under the face, not squeezed beside the name"
    assert "var(--cb-cap-1)" in phone[P + " > .scenbar .ssel"] and "appearance: none" in phone[P + " > .scenbar .ssel"], "the dropdown is a cabinet pushbutton"
    assert "min-width: 44px" in phone[P + " > .scenbar #d_edit"], "44 px controls (the drawer's controls get theirs from the shared touch-target rule)"
    assert not re.search(r"min-height:\s*(?:[0-3]?\d|4[0-3])px", " ".join(phone.values())), "nothing shrinks a control below 44 px"
    tiny = {s: " ".join(b.split()) for m, ss, b in rules if m == "(max-width: 360px)" for s in ss}
    assert tiny[P + " > .plate .sticker"] == "display: none;", "the sticker gives way on the narrowest phones"
    knob = [(m, b) for m, ss, b in rules if any(s.endswith(" .knob") for s in ss) and "display: block" in b]
    assert [m for m, _ in knob] == ["(min-width: 701px)"], "the knob shows only wider than 700 px; at 700 px or less it stays hidden"
    assert all(m != "(max-width: 600px)" for m, ss, b in rules if any(".knob" in s for s in ss)), "no phone rule touches the knob"


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_retro_dashboard_page_is_gunmetal_not_oxblood(theme):
    """Retro Dashboard (2026-10-02): the bar, chips and page ground take a neutral grey from the cabinet's steel; the accent is the lamp amber."""
    p, old = _palette("retro-dashboard", theme), _palette("retro", theme)
    for tok in ("--bg", "--panel", "--panel2", "--line"):
        rgb = [int(p[tok][i:i + 2], 16) for i in (1, 3, 5)]
        assert max(rgb) - min(rgb) <= 12, f"{theme} {tok} {p[tok]} is not a neutral grey"
        assert p[tok] != old[tok]
    acc = [int(p["--cyan"][i:i + 2], 16) for i in (1, 3, 5)]
    assert acc[0] > acc[1] > acc[2], f"{theme}: the active view and the scrubber are amber, {p['--cyan']}"
    assert re.search(r':root\[data-skin="retro"\]\[data-view="v0"\] \{[^}]*--bg: var\(--rd-bg\)', _css()), "the re-point block uses tokens only"
    js = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)
    assert "document.documentElement.setAttribute('data-view', id)" in js, "show() tells the CSS which view is up"
