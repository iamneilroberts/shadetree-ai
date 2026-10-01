# Console stage 1 (skin and shared parts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the console a Plain/Retro skin (each with dark and light) driven by one `data-skin` attribute, with every colour a CSS variable, and add the shared parts stage 2 builds the Dashboard from: Panel, Gauge (dial, LED bar, seven-segment) and the All readings table as a component, with no server or data change.

**Architecture:** Colours move into token blocks on `:root` (Plain dark and light stay byte-for-byte today's values; Retro dark and light are new blocks keyed on `:root[data-skin="retro"]`), and the retro device palette moves out of `.retro` so any view can use it. The shared parts are plain page functions in the one inline script (`panel`, `gauges`/`gaugeModel` built on the existing `seven`, a `dialSvg` split out of `meter`, and `pidRows`/`pidTableEl` lifted from `renderReadings`), reachable by the Node page test through a `window.__shadetreeParts` hook a browser never defines. A temporary `#vp` section (no tab) shows the parts for Neil's screenshot pass until stage 2's Dashboard replaces it.

**Tech Stack:** One self-contained HTML file (vanilla ES5-style JS, CSS custom properties, inline SVG), Node page test (`tests/js/page_logic_test.js`, fake DOM), pytest (`tests/test_console_page.py`).

**Spec:** `docs/superpowers/specs/2026-10-01-console-coherence-design.md` (stage 1, retained features, non-goals). Console source of truth: `docs/design.md` §7b. Both spec and this plan are untracked files in the main checkout (`/home/neil/dev/obd-reader`); read them there, the worktree will not contain them.

## Global Constraints

- One file: "splitting the page into multiple files or adding a framework" is a non-goal; "the one-file, hash-pinned-CSP design stays" (one `<script>`, one `<style>`, no external URLs).
- No new libraries, no new dependencies.
- No server or data changes: "No server or data changes" (spec stage 1); nothing under `src/obd_reader/` other than `web/console.html` changes.
- Read-only: "Read-only, enforced in code ... Never clear, write, actuate. No tool takes a raw command string." Stage 1 adds no route and no request.
- Stage files by name (`git add <file>`, never `-A`/`.`); commit messages carry no attribution lines; commit only on the stage-1 worktree branch.
- Merge to `main` and push only when Neil says "merge and push".
- Public repo, MIT: "never commit real snapshots/transcripts (VINs), secrets"; no tokens or VIN-shaped text in tests or fixtures.
- Retained features, each still reachable: "Capture all supported, Demo button, Save run, replay with the Examples/My runs picker and `?example=`, Mode 06 section, All readings stats (Now, Min, Max, Avg, Std, Samples, last-seen, min/max time), Units, Theme, "?" help popups, codes and readiness, Guided test, upload, transport bar."
- "Agents cannot see a browser: Neil does a desktop and phone screenshot pass before each merge." Never say a page was viewed.
- The Plain skin (the default on a desktop) must look exactly as it does at `ce159c5`; `same_look.py` (Task 2) proves it after every CSS change.

## Review Focus

Failure modes most likely to bite a user that the happy path would not exercise; each has a test in the owning task, tagged `Review Focus N` in the test source:

1. **Browser storage unusable:** `localStorage` throws (Safari private mode, blocked site data) or holds a value this build does not know (`'Retro'`, `''`, JSON from an old build). The page must still choose a skin from the viewport and the button must still toggle. → Task 3, node block "Skin".
2. **A skin and theme combination is unreadable:** a token missing from one block silently falls through to another skin's value, or a new palette has low contrast. → Task 3 `test_every_skin_and_theme_keeps_text_readable` (all four combos, 13 text/background pairs, WCAG AA 4.5:1) and Task 2 `test_the_plain_palette_is_todays`.
3. **A gauge is given a PID missing from the run** (stage 2 scenarios name PIDs a given car may not report): it must be dimmed and say "not in this run", with no needle, no lit LED and no digits; an idle console says "not sampling"; a PID in the run with no sample yet says "waiting"; a channel name from an uploaded run cannot inject markup. → Task 5, node block "Gauge".
4. **The table component gets an empty, huge (64, the run-file maximum), duplicated or unknown PID list:** no rows, 64 rows, each PID once in the given order, dashes for a PID not in the run, and the All readings table beside it unchanged. → Task 6, node block "PID table".
5. **A very narrow viewport (360 px phone):** gauges fit two across inside the 16 px gutters, long names shorten with an ellipsis instead of widening the page, and the table scrolls inside its card. → Task 5 `test_shared_parts_fit_a_phone_width`, plus Neil's phone pass (Task 8).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/obd_reader/web/console.html` (modify) | Token blocks, skin switch, `dialSvg`, Panel, Gauge, PID table component, `#vp` preview |
| `tests/js/page_logic_test.js` (modify) | Harness: query-aware `matchMedia`, `page.narrow`, `env.parts()`; tests for skin, Panel, Gauge, PID table, preview |
| `tests/test_console_page.py` (modify) | Retained-features checklist, size budget, colour-token, Plain-palette, contrast and narrow-viewport tests |
| `README.md`, `docs/design.md` (modify, Task 8) | One row / one sentence each |
| `$SCRATCH/tokenize_colours.py`, `$SCRATCH/same_look.py`, `$SCRATCH/console.orig.html` (scratch, never committed) | One-off literal-to-token rewrite and the Plain-look identity check |

`$SCRATCH` below means your session scratchpad directory, as an absolute path; substitute it in every command (shell variables do not persist between calls).

Commands run from the worktree root `/home/neil/dev/obd-reader-console-stage1`:
- Node page test: `node tests/js/page_logic_test.js src/obd_reader/web/console.html` (prints `page logic OK`, or `FAIL <message>` and exits 1)
- Page pytest: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py`
- Full suite: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q` (`PYTHONPATH=src` puts the worktree's package ahead of the editable install, which points at the main checkout)

Line numbers in this plan are those at `ce159c5` and drift once Task 2 lands; always match by the quoted text. Insertion anchors used below (all exist at `ce159c5`): CSS ends with `  button.b:disabled { opacity: .45; cursor: not-allowed; }` before `</style>`; the shared-parts JS goes immediately above `  /* ---------- Overview ---------- */`, each task's block under the previous one; the script ends with `  loadHelp();` then `})();`.

---

### Task 0: Worktree and baseline

**Files:** none changed.

**Interfaces:** Consumes nothing. Produces the branch `feat/console-stage1-skin` in `/home/neil/dev/obd-reader-console-stage1`.

- [ ] **Step 1: Check for other sessions' work** — `cd /home/neil/dev/obd-reader && git status --short && git worktree list`. Expected: only `?? docs/superpowers/plans/2026-10-01-console-stage1-skin-and-shared-parts.md` and `?? docs/superpowers/specs/2026-10-01-console-coherence-design.md`, one worktree at `ce159c5` or later. Anything else uncommitted belongs to another session: stop and ask Neil.

- [ ] **Step 2: Create the worktree** — `git -C /home/neil/dev/obd-reader worktree add /home/neil/dev/obd-reader-console-stage1 -b feat/console-stage1-skin main`

- [ ] **Step 3: Baseline** — `cd /home/neil/dev/obd-reader-console-stage1 && node tests/js/page_logic_test.js src/obd_reader/web/console.html && PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: `page logic OK` and `639 passed`. A different count means main moved: note the new number and use it below.

- [ ] **Step 4: Keep the original page for the identity check** — `git -C /home/neil/dev/obd-reader-console-stage1 show ce159c5:src/obd_reader/web/console.html > $SCRATCH/console.orig.html && wc -c $SCRATCH/console.orig.html` (expected `92165`).

---

### Task 1: Retained-features checklist and size budget (guard)

A guard, not a feature: it passes on today's page and must keep passing after every later task.

**Files:**
- Modify: `tests/test_console_page.py` (append at the end)

**Interfaces:**
- Consumes: the page markup and script at `ce159c5`.
- Produces: `RETAINED: dict[str, list[str]]` (feature name to required substrings; Task 3 adds `"Skin"`), `test_retained_feature_is_still_on_the_page[<feature>]`, `test_page_stays_one_file_under_its_size_budget` (112,000 bytes; stage 2 raises it on purpose).

- [ ] **Step 1: Write the test** — append to `tests/test_console_page.py`:

```python


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
```

- [ ] **Step 2: Run it** — `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py 2>&1 | tail -1`
Expected: `22 passed` (8 existing + 13 features + 1 size). It passes now by design; it is the checklist the spec asks for "per stage".

- [ ] **Step 3: Commit** — `git add tests/test_console_page.py && git commit -m "test: retained-features checklist for the console (each control the coherence spec keeps is still in the page) and a 112,000-byte one-file size budget"`

---

### Task 2: Every colour is a CSS variable (Plain look unchanged)

**Files:**
- Modify: `src/obd_reader/web/console.html` — CSS lines 8-14 (`:root`), 22 (`.banner`), 84-194 (retro rules), 371-415 (inline `--c` styles), 1035-1053 (`meter`), 1084-1103 (seven-segment colours, handheld MIL)
- Modify: `tests/test_console_page.py` (append)
- Scratch: `$SCRATCH/tokenize_colours.py`, `$SCRATCH/same_look.py`

**Interfaces:**
- Consumes: `seven(el, v, digits, dp, color, h)`, `esc(x)` (unchanged).
- Produces:
  - Device palette tokens on `:root` (same values in every skin and theme): `--sil --ghost --glow --ink2 --mut --retro-ink --rail --rail-rivet --rail-tex --rail-edge --face --face-bd --face-ink --pan --pan-bd --plate-bg --plate-ink --plate-ink2 --bench --scale --win-bd --win-bg --led-off --led-g --led-y --led-r --led-zero --seg-red --code-amber --lamp-lit --lens-bd --lens-red --lens-grn --lens-amb --lens-red-lit --lens-amb-lit --lens-grn-lit --screw --screw-slot --rocker --rocker-bd --rocker-ink --rocker-sh --nav-on --nav-on-bd --on-amber --on-red --crow-line --cdesc --chint --wait-ink --hlive-off --meter-face --meter-rim --meter-zone --meter-ink --meter-ink2 --meter-needle`; plus `--banner-ink` in the Plain `:root` block.
  - `dialSvg(v: number|null, lo: number, hi: number, majors: number, zones: Array<{from: number, to: number, s: 'ok'|'watch'|'out'}>, label: string, div?: number) -> string` — the meter face as SVG markup; `v` null draws no needle; `label` is escaped.
  - `meter(el, v, lo, hi, majors, redFrom, label, div)` — signature and geometry unchanged; draws through `dialSvg` (needle still rests at `lo` when `v` is null, as today).
  - Dial CSS classes reading gauge tokens: `svg.dial .df/.da/.dt/.dx/.dn/.dh/.z-ok/.z-watch/.z-out` on `--g-face --g-rim --g-ink --g-ink2 --g-needle --g-z-ok --g-z-watch --g-z-out`; `.retro` sets the meter values for those, so the Analyzer meters are unchanged.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_console_page.py`:

```python


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
```

- [ ] **Step 2: Run to verify failure** — `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py 2>&1 | grep -E "FAILED|passed|failed"`
Expected: `FAILED ...test_the_plain_palette_is_todays` (no `--banner-ink` yet), `FAILED ...test_colours_live_only_in_the_token_blocks`, `2 failed, 22 passed`.

- [ ] **Step 3: Write the rewrite script** — create `$SCRATCH/tokenize_colours.py` (not committed). Each pair must occur exactly the stated number of times or the script stops without writing:

```python
"""Stage 1, Task 2: move every colour literal in console.html into a CSS variable (one-off; not committed)."""
import sys
from pathlib import Path

page = Path(sys.argv[1])
html = page.read_text(encoding="utf-8")

OLD_RETRO = """  .retro { --sil: "Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif; --ghost: .16; --glow: 3px;
         --ink2: #4a4a4c; --mut: #a39b88; font: 14px/1.45 var(--sil); color: #ece6d6;
         --rail: linear-gradient(90deg, #3a0f0e, #7d2724 22%, #a5423b 34%, #74221f 62%, #3f100f); --rail-rivet: radial-gradient(circle at 50% 28px, #e4e4e2 0 2.5px, #2b2b2c 3px 5px, transparent 5.5px) 0 0 / 100% 84px repeat-y; --rail-tex: repeating-linear-gradient(90deg, rgba(255,255,255,.05) 0 1px, rgba(0,0,0,.08) 1px 2px); --rail-edge: rgba(230,230,228,.35); --face: linear-gradient(#e9e9e6, #d6d6d3); --face-bd: #2b2b2c; --face-ink: #161617; --ink2: #4a4a4c; --pan: #b9babc; --pan-bd: #7a7b7e; --plate-bg: #141415; --plate-ink: #f4f4f1; --plate-ink2: #a9aaad; --bench: #a6a7aa; --scale: #232324; --meter-face: #f6f5ef; --win-bd: #2b2b2c; }
"""
NEW_RETRO = """  /* retro device palette: the Analyzer and Handheld faces read these in every skin and theme; the Retro skin also uses them for any view */
  :root {
    --sil: "Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif; --ghost: .16; --glow: 3px; --ink2: #4a4a4c; --mut: #a39b88; --retro-ink: #ece6d6;
    --rail: linear-gradient(90deg, #3a0f0e, #7d2724 22%, #a5423b 34%, #74221f 62%, #3f100f); --rail-rivet: radial-gradient(circle at 50% 28px, #e4e4e2 0 2.5px, #2b2b2c 3px 5px, transparent 5.5px) 0 0 / 100% 84px repeat-y; --rail-tex: repeating-linear-gradient(90deg, rgba(255,255,255,.05) 0 1px, rgba(0,0,0,.08) 1px 2px); --rail-edge: rgba(230,230,228,.35);
    --face: linear-gradient(#e9e9e6, #d6d6d3); --face-bd: #2b2b2c; --face-ink: #161617; --pan: #b9babc; --pan-bd: #7a7b7e; --plate-bg: #141415; --plate-ink: #f4f4f1; --plate-ink2: #a9aaad; --bench: #a6a7aa; --scale: #232324; --win-bd: #2b2b2c;
    --win-bg: #0d0a09; --led-off: rgba(255,255,255,.07); --led-g: #3fe06a; --led-y: #ffc233; --led-r: #ff4a3a; --led-zero: #d9d2bd; --seg-red: #ff3b2b; --code-amber: #ffb62e;
    --lamp-lit: #fff1cf; --lens-bd: #6c6555; --lens-red: radial-gradient(circle at 35% 30%, #5a4a4a, #2a1c1c 70%); --lens-grn: radial-gradient(circle at 35% 30%, #4a5a4a, #1c2a1c 70%); --lens-amb: radial-gradient(circle at 35% 30%, #5a5040, #2a2216 70%);
    --lens-red-lit: radial-gradient(circle at 35% 30%, #ffd0c8, #ff4a3a 55%, #b3170b); --lens-amb-lit: radial-gradient(circle at 35% 30%, #fff0c0, #ffc233 55%, #b37c05); --lens-grn-lit: radial-gradient(circle at 35% 30%, #d6ffe0, #3fe06a 55%, #0e8a30);
    --screw: radial-gradient(circle at 35% 30%, #f1f1ee, #7d8288); --screw-slot: #454a4f; --rocker: linear-gradient(#5a5c60, #2b2c2f); --rocker-bd: #1b1c1e; --rocker-ink: #f1ead4; --rocker-sh: #101112;
    --nav-on: #e3b04b; --nav-on-bd: #a5782a; --on-amber: #241a06; --on-red: #1a0503; --crow-line: #2a2320; --cdesc: #f3ecd8; --chint: #b9ae94; --wait-ink: #a9aaad; --hlive-off: #ff8a7a;
    --meter-face: #f6f5ef; --meter-rim: #7d765f; --meter-zone: #c9382a; --meter-ink: #2a2723; --meter-ink2: #5b5547; --meter-needle: #b22a1c;
  }
  .retro { font: 14px/1.45 var(--sil); color: var(--retro-ink);
           --g-face: var(--meter-face); --g-rim: var(--meter-rim); --g-ink: var(--meter-ink); --g-ink2: var(--meter-ink2); --g-needle: var(--meter-needle); --g-z-out: var(--meter-zone); }
"""

# (old, new, how many times old must occur)
PAIRS = [
    (OLD_RETRO, NEW_RETRO, 1),
    ("--on-accent: #06222c; --banner: #f2a93b; --msg-bg: #2a2114;", "--on-accent: #06222c; --banner: #f2a93b; --banner-ink: #1a1204; --msg-bg: #2a2114;", 1),
    (".banner { background: var(--banner); color: #1a1204;", ".banner { background: var(--banner); color: var(--banner-ink);", 1),
    (".retro .win { background: #0d0a09;", ".retro .win { background: var(--win-bg);", 1),
    ("gap: 3px; background: #0d0a09;", "gap: 3px; background: var(--win-bg);", 1),
    ("border-radius: 2px; background: rgba(255,255,255,.07); }", "border-radius: 2px; background: var(--led-off); }", 1),
    (".retro .leds i.g { background: #3fe06a; box-shadow: 0 0 6px #3fe06a; }", ".retro .leds i.g { background: var(--led-g); box-shadow: 0 0 6px var(--led-g); }", 1),
    (".retro .leds i.y { background: #ffc233; box-shadow: 0 0 6px #ffc233; }", ".retro .leds i.y { background: var(--led-y); box-shadow: 0 0 6px var(--led-y); }", 1),
    (".retro .leds i.r { background: #ff4a3a; box-shadow: 0 0 6px #ff4a3a; }", ".retro .leds i.r { background: var(--led-r); box-shadow: 0 0 6px var(--led-r); }", 1),
    ("border-bottom: 3px solid #d9d2bd;", "border-bottom: 3px solid var(--led-zero);", 1),
    (".retro .lampbox.lit { color: #fff1cf; }", ".retro .lampbox.lit { color: var(--lamp-lit); }", 1),
    ("border: 3px solid #6c6555; background: radial-gradient(circle at 35% 30%, #5a4a4a, #2a1c1c 70%); }", "border: 3px solid var(--lens-bd); background: var(--lens-red); }", 1),
    (".retro .lens.grn { background: radial-gradient(circle at 35% 30%, #4a5a4a, #1c2a1c 70%); }", ".retro .lens.grn { background: var(--lens-grn); }", 1),
    (".retro .lens.amb { background: radial-gradient(circle at 35% 30%, #5a5040, #2a2216 70%); }", ".retro .lens.amb { background: var(--lens-amb); }", 1),
    ("background: radial-gradient(circle at 35% 30%, #ffd0c8, #ff4a3a 55%, #b3170b); box-shadow: 0 0 12px #ff4a3a; }", "background: var(--lens-red-lit); box-shadow: 0 0 12px var(--led-r); }", 1),
    ("background: radial-gradient(circle at 35% 30%, #fff0c0, #ffc233 55%, #b37c05); box-shadow: 0 0 12px #ffc233; }", "background: var(--lens-amb-lit); box-shadow: 0 0 12px var(--led-y); }", 1),
    ("background: radial-gradient(circle at 35% 30%, #d6ffe0, #3fe06a 55%, #0e8a30); box-shadow: 0 0 12px #3fe06a; }", "background: var(--lens-grn-lit); box-shadow: 0 0 12px var(--led-g); }", 1),
    ("background: radial-gradient(circle at 35% 30%, #f1f1ee, #7d8288);", "background: var(--screw);", 1),
    ("height: 2px; background: #454a4f;", "height: 2px; background: var(--screw-slot);", 1),
    ("border: 2px solid #1b1c1e; background: linear-gradient(#5a5c60, #2b2c2f); color: #f1ead4;", "border: 2px solid var(--rocker-bd); background: var(--rocker); color: var(--rocker-ink);", 2),
    ("box-shadow: 0 2px 0 #101112; }", "box-shadow: 0 2px 0 var(--rocker-sh); }", 1),
    ("box-shadow: 0 1px 0 #101112; }", "box-shadow: 0 1px 0 var(--rocker-sh); }", 1),
    (".retro .clist { background: #0d0a09;", ".retro .clist { background: var(--win-bg);", 1),
    ("border-bottom: 1px solid #2a2320; }", "border-bottom: 1px solid var(--crow-line); }", 1),
    ("color: #ffb62e; text-shadow: 0 0 var(--glow) #ffb62e;", "color: var(--code-amber); text-shadow: 0 0 var(--glow) var(--code-amber);", 1),
    (".retro .cst.stored { background: #ff4a3a; color: #1a0503; }", ".retro .cst.stored { background: var(--led-r); color: var(--on-red); }", 1),
    (".retro .cst.pending { background: #ffc233; color: #241a06; }", ".retro .cst.pending { background: var(--led-y); color: var(--on-amber); }", 1),
    (".retro .cdesc { color: #f3ecd8;", ".retro .cdesc { color: var(--cdesc);", 1),
    ("font: 400 12.5px var(--sil); color: #b9ae94; }", "font: 400 12.5px var(--sil); color: var(--chint); }", 1),
    (".retro .cnone { color: #3fe06a;", ".retro .cnone { color: var(--led-g);", 1),
    ("text-shadow: 0 0 var(--glow) #3fe06a; }", "text-shadow: 0 0 var(--glow) var(--led-g); }", 1),
    ("letter-spacing: .08em; color: #ffb62e; }", "letter-spacing: .08em; color: var(--code-amber); }", 1),
    (".retro .hh-top .n.zero { color: #3fe06a; }", ".retro .hh-top .n.zero { color: var(--led-g); }", 1),
    (".retro .hh-nav button.on { background: #e3b04b; color: #241a06; border-color: #a5782a; }", ".retro .hh-nav button.on { background: var(--nav-on); color: var(--on-amber); border-color: var(--nav-on-bd); }", 1),
    (".retro .hcode { background: #0d0a09;", ".retro .hcode { background: var(--win-bg);", 1),
    (".retro .cnone.wait { color: #a9aaad;", ".retro .cnone.wait { color: var(--wait-ink);", 1),
    ("letter-spacing: .12em; color: #a9aaad; }", "letter-spacing: .12em; color: var(--wait-ink); }", 1),
    (".retro .hlive.on { color: #3fe06a; } .retro .hlive.off { color: #ff8a7a; }", ".retro .hlive.on { color: var(--led-g); } .retro .hlive.off { color: var(--hlive-off); }", 1),
    # markup: the glow colour of each seven-segment window
    ('style="--c:#ff3b2b"', 'style="--c:var(--seg-red)"', 3),
    ('style="--c:#ffb62e"', 'style="--c:var(--code-amber)"', 4),
    ('style="--c:#3fe06a"', 'style="--c:var(--led-g)"', 2),
    # script: seven-segment digit colours and the handheld's lit MIL lens
    ("'#ff3b2b'", "'var(--seg-red)'", 3),
    ("'#3fe06a'", "'var(--led-g)'", 3),
    ("'#ffb62e'", "'var(--code-amber)'", 4),
    ("';background:radial-gradient(circle at 35% 30%,#ffd0c8,#ff4a3a 55%,#b3170b);box-shadow:0 0 12px #ff4a3a'", "';background:var(--lens-red-lit);box-shadow:0 0 12px var(--led-r)'", 1),
]

for old, new, n in PAIRS:
    got = html.count(old)
    assert got == n, f"expected {n} of {old[:70]!r}, found {got}"
    html = html.replace(old, new)
page.write_text(html, encoding="utf-8")
print(f"replaced {len(PAIRS)} patterns")
```

Moving `--ghost` and `--glow` to `:root` matters beyond tidiness: `seven()` writes `fill-opacity:var(--ghost)`, which outside `.retro` was undefined, so any seven-segment display outside the Analyzer/Handheld would have lit every segment.

- [ ] **Step 4: Run the script** — `python3 $SCRATCH/tokenize_colours.py src/obd_reader/web/console.html`
Expected: `replaced 45 patterns`. An `AssertionError` names the pattern that did not match: fix the pair, never loosen the count.

- [ ] **Step 5: Split `meter` into `dialSvg` with classes** — SVG presentation attributes cannot take `var()`, so colours move to classes. Replace the whole `function meter(el, v, lo, hi, majors, redFrom, label, div) { ... }` (from that line through the line `    var keep = el.querySelector('.lab'); el.innerHTML = (keep ? keep.outerHTML : '') + s;` and its closing `  }`) with:

```js
  function dialSvg(v, lo, hi, majors, zones, label, div) {   // the analyzer meter face; zones [{from, to, s: 'ok'|'watch'|'out'}] are coloured arcs; v null draws no needle
    div = div || 1;
    var cx = 110, cy = 118, r = 92, a0 = -50, a1 = 50, s = '<svg class="dial" viewBox="0 0 220 128" role="img" aria-label="' + esc(label) + '">';
    s += '<rect class="df" x="2" y="2" width="216" height="124" rx="6" stroke-width="2"/>';
    function P(val, rad) { var a = (a0 + (a1 - a0) * (val - lo) / (hi - lo)) * Math.PI / 180; return [cx + rad * Math.sin(a), cy - rad * Math.cos(a)]; }
    zones.forEach(function (z) { var p = P(z.from, r), q = P(z.to, r); s += '<path class="z-' + z.s + '" d="M' + p[0] + ' ' + p[1] + ' A' + r + ' ' + r + ' 0 0 1 ' + q[0] + ' ' + q[1] + '" stroke-width="6" fill="none"/>'; });
    var p0 = P(lo, r), p1 = P(hi, r); s += '<path class="da" d="M' + p0[0] + ' ' + p0[1] + ' A' + r + ' ' + r + ' 0 0 1 ' + p1[0] + ' ' + p1[1] + '" stroke-width="2" fill="none"/>';
    for (var i = 0; i <= majors; i++) {
      var val = lo + (hi - lo) * i / majors, o = P(val, r + 2), inn = P(val, r - 12), tx = P(val, r - 24);
      s += '<line class="dt" x1="' + o[0] + '" y1="' + o[1] + '" x2="' + inn[0] + '" y2="' + inn[1] + '" stroke-width="2.4"/>';
      s += '<text x="' + tx[0] + '" y="' + (tx[1] + 4) + '" font-size="13" font-weight="700" text-anchor="middle" font-family="Helvetica,Arial,sans-serif">' + (Math.round(val / div * 10) / 10) + '</text>';
      if (i < majors) for (var j = 1; j < 4; j++) { var mv = val + (hi - lo) / majors * j / 4, m1 = P(mv, r + 1), m2 = P(mv, r - 6); s += '<line class="dt" x1="' + m1[0] + '" y1="' + m1[1] + '" x2="' + m2[0] + '" y2="' + m2[1] + '" stroke-width="1.2"/>'; }
    }
    if (div !== 1) s += '<text class="dx" x="12" y="22" font-size="10" font-weight="700" text-anchor="start" font-family="Helvetica,Arial,sans-serif" letter-spacing="1.5">x' + div + ' RPM</text>';
    if (v !== null && v !== undefined) { var nv = P(Math.max(lo, Math.min(hi, v)), r - 6); s += '<line class="dn" x1="' + cx + '" y1="' + cy + '" x2="' + nv[0] + '" y2="' + nv[1] + '" stroke-width="3" stroke-linecap="round"/>'; }
    return s + '<circle class="dh" cx="' + cx + '" cy="' + cy + '" r="7"/></svg>';
  }
  function meter(el, v, lo, hi, majors, redFrom, label, div) {   // the analyzer's meters: one red zone from redFrom, and the needle rests at lo when there is no value
    var keep = el.querySelector('.lab');
    el.innerHTML = (keep ? keep.outerHTML : '') + dialSvg(v === null ? lo : v, lo, hi, majors, redFrom === null ? [] : [{ from: redFrom, to: hi, s: 'out' }], label, div);
  }
```

Then add the dial CSS directly under the line `  .retro .meter svg { width: 100%; display: block; }`:

```css
  svg.dial .df { fill: var(--g-face); stroke: var(--g-rim); }
  svg.dial .da, svg.dial .dt { stroke: var(--g-ink); }
  svg.dial text, svg.dial .dh { fill: var(--g-ink); }
  svg.dial text.dx { fill: var(--g-ink2); }
  svg.dial .dn { stroke: var(--g-needle); }
  svg.dial .z-ok { stroke: var(--g-z-ok); } svg.dial .z-watch { stroke: var(--g-z-watch); } svg.dial .z-out { stroke: var(--g-z-out); }
```

- [ ] **Step 6: Write the identity check** — create `$SCRATCH/same_look.py` (not committed; Tasks 3, 6 and 8 rerun it):

```python
"""One-off check that tokenizing changed no colour: every rule of OLD and NEW, with var() resolved, must match.

Usage: python3 same_look.py OLD.html NEW.html
Prints 'same look' or the first rules that differ. Rules new in NEW (svg.dial ...) are listed, not compared.
"""
import re
import sys


def style(path):
    h = open(path, encoding="utf-8").read()
    css = re.search(r"<style>(.*?)</style>", h, re.S).group(1)
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S), h


def rules(css):
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def decls(body):
    out = []
    for part in body.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out.append((k.strip(), " ".join(v.split())))
    return out


def tokens(rs, theme):
    t = {}
    for sel, body in rs:
        if sel == ":root" or (theme == "light" and sel == ':root[data-theme="light"]') or sel == ".retro":
            t.update({k: v for k, v in decls(body) if k.startswith("--")})
    return t


def resolve(v, t, depth=0):
    if depth > 10:
        raise ValueError("var loop: " + v)
    new = re.sub(r"var\((--[\w-]+)\)", lambda m: t.get(m.group(1), m.group(0)), v)
    return new if new == v else resolve(new, t, depth + 1)


def look(path, theme):
    css, _ = style(path)
    rs = rules(css)
    t = tokens(rs, theme)
    # the PID table task unscopes '#v6 table.rd' and '#v6 .rwrap' on purpose: compare those rules under their new selectors
    return [(re.sub(r"#v6 (table\.rd|\.rwrap)", r"\1", sel), [(k, resolve(v, t)) for k, v in decls(body) if not k.startswith("--")])
            for sel, body in rs if not sel.startswith(":root") and not all(k.startswith("--") for k, _ in decls(body))]


old_path, new_path = sys.argv[1], sys.argv[2]
bad = 0
for theme in ("dark", "light"):
    old = look(old_path, theme)
    new = [r for r in look(new_path, theme) if r[0] in {s for s, _ in old}]
    extra = sorted({s for s, _ in look(new_path, theme)} - {s for s, _ in old})
    if [s for s, _ in old] != [s for s, _ in new]:
        print(theme, "rule order or set changed"); bad += 1
    for (s1, d1), (s2, d2) in zip(old, new):
        if d1 != d2:
            print(theme, "DIFF", s1, "\n  old", d1, "\n  new", d2); bad += 1
    print(theme, "new rules (not compared):", extra)

# meter geometry: strip colour attributes and classes, then the SVG must be the same
def meter_svg(path, args):
    _, h = style(path)
    js = re.search(r"<script>(.*?)</script>", h, re.S).group(1)
    src = js[js.index("  function meter("):js.index("  function lamp(")]
    if "function dialSvg" in js and "function dialSvg" not in src:
        src = js[js.index("  function dialSvg("):js.index("  function meter(")] + src
    esc = "function esc(x) { return String(x).replace(/[&<>\"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;' }[c]; }); }"
    return src, esc


import json, subprocess
cases = [[14.2, 11, 16, 5, 15, "volts"], [None, 11, 16, 5, 15, "volts"], [700, 0, 4000, 4, 3500, "tachometer", 1000], [90, 20, 120, 5, 105, "coolant"], [5, 0, 10, 5, None, "x"]]
outs = []
for path in (old_path, new_path):
    src, esc = meter_svg(path, None)
    prog = esc + src + "var out = []; var cases = " + json.dumps(cases) + ";\n" + \
        "cases.forEach(function (c) { var el = { querySelector: function () { return null; } }; meter.apply(null, [el].concat(c)); out.push(el.innerHTML); });\n" + \
        "console.log(JSON.stringify(out));"
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=True)
    outs.append([re.sub(r' (?:class|fill|stroke)="[^"]*"', "", s).replace("fill=\"none\"", "") for s in json.loads(r.stdout)])
for i, (a, b) in enumerate(zip(*outs)):
    if a != b:
        print("METER DIFF case", cases[i], "\n old", a[:300], "\n new", b[:300]); bad += 1
print("same look" if not bad else f"{bad} differences")
```

- [ ] **Step 7: Run everything** — `python3 $SCRATCH/same_look.py $SCRATCH/console.orig.html src/obd_reader/web/console.html | tail -1 && node tests/js/page_logic_test.js src/obd_reader/web/console.html && PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py 2>&1 | tail -1`
Expected: `same look`, `page logic OK`, `24 passed`.

- [ ] **Step 8: Prove the check can fail** — `sed 's/--led-g: #3fe06a/--led-g: #3fe06b/' src/obd_reader/web/console.html > $SCRATCH/mut.html && python3 $SCRATCH/same_look.py $SCRATCH/console.orig.html $SCRATCH/mut.html | tail -1`
Expected: a non-zero `N differences` line.

- [ ] **Step 9: Commit** — `git add src/obd_reader/web/console.html tests/test_console_page.py && git commit -m "feat: console colours are CSS variables: the retro device palette moves from .retro to :root, every colour literal in the CSS, markup and script becomes a token, and the meter draws through dialSvg with classes; the Plain look is unchanged (resolved-rule and meter-geometry check)"`

---

### Task 3: Skin system (Plain/Retro, each dark and light)

**Files:**
- Modify: `src/obd_reader/web/console.html` — first `:root` block (append shared-part tokens), new Retro blocks after `:root[data-theme="light"]`, header button after `#themeBtn` (line 292), `PALS` (line 460), `setTheme` (line 962-966), new skin code above `$('unitsBtn').addEventListener('click', ...)`
- Modify: `tests/js/page_logic_test.js` — `makeEnv` matchMedia (line 51), new block before `console.log('page logic OK');`
- Modify: `tests/test_console_page.py` — `RETAINED` gets `"Skin"`; append the contrast test

**Interfaces:**
- Consumes: `THEME`, `setTheme(t)`, `pickTheme` pattern, `render()`.
- Produces:
  - `pickSkin(stored: string|null, narrow: boolean) -> 'plain'|'retro'` — a stored `'plain'`/`'retro'` wins, anything else is ignored; then Retro when `narrow`, else Plain.
  - `setSkin(s)`, `SKIN` (current skin), `setPal()` (canvas `PAL` from `PALS[SKIN + '-' + THEME]`).
  - `<html data-skin="plain|retro">` beside `data-theme`; storage key `shadetree.skin`; `#skinBtn` labelled with the skin a click switches to ("Skin: Retro" on Plain), as Theme is.
  - "Narrow" means `matchMedia('(max-width: 600px)')` (the spec's "under about 600 px").
  - Token sets: `:root[data-skin="retro"]`, `:root[data-skin="retro"][data-theme="light"]`; shared-part tokens on every skin: `--pn-plate-bg --pn-plate-ink --g-face --g-rim --g-ink --g-ink2 --g-needle --g-z-ok --g-z-watch --g-z-out --g-seg --g-ok --g-warn --g-bad --g-win --g-led-off --g-glow`.
  - Harness: `makeEnv(..., page)` accepts `page.narrow`; its `matchMedia` answers width queries from `narrow` and colour-scheme queries from `prefersLight`.

- [ ] **Step 1: Make the harness's matchMedia query-aware** — in `tests/js/page_logic_test.js` replace

```js
  if (page.prefersLight !== undefined) sandbox.window.matchMedia = (q) => ({ matches: /light/.test(q) === page.prefersLight });
```

with

```js
  if (page.prefersLight !== undefined || page.narrow !== undefined)   // a width query answers page.narrow, a colour-scheme query page.prefersLight
    sandbox.window.matchMedia = (q) => ({ matches: /max-width/.test(q) ? !!page.narrow : /light/.test(q) === !!page.prefersLight });
```

and in the `makeEnv` comment change `prefersLight, storageThrows` to `prefersLight, narrow, storageThrows`. (Today's fake answers any query without "light" as `!prefersLight`, so a width query would have reported a phone in every theme test.)

- [ ] **Step 2: Write the failing node test** — insert immediately before `  console.log('page logic OK');`:

```js
  // Skin: a stored choice beats the viewport; a bad stored value is ignored; Plain on a desktop, Retro on a phone; blocked storage is tolerated (Review Focus 1)
  const skin = (e) => e.el('html').getAttribute('data-skin');
  assert.strictEqual(skin(await thEnv({}, {})), 'plain', 'no matchMedia: Plain, as the page always was');
  assert.strictEqual(skin(await thEnv({}, { narrow: false })), 'plain', 'desktop width: Plain');
  assert.strictEqual(skin(await thEnv({}, { narrow: true })), 'retro', 'phone width: Retro');
  assert.strictEqual(skin(await thEnv({ 'shadetree.skin': 'plain' }, { narrow: true })), 'plain', 'a stored Plain beats a phone');
  assert.strictEqual(skin(await thEnv({ 'shadetree.skin': 'retro' }, { narrow: false })), 'retro', 'a stored Retro beats a desktop');
  for (const bad of ['Retro', 'oxblood', '', 'null', '{"skin":"retro"}']) {
    assert.strictEqual(skin(await thEnv({ 'shadetree.skin': bad }, { narrow: false })), 'plain', 'a bad stored value is ignored: ' + bad);
    assert.strictEqual(skin(await thEnv({ 'shadetree.skin': bad }, { narrow: true })), 'retro', 'and the viewport decides: ' + bad);
  }
  const skStore = {}, sk1 = await thEnv(skStore, { narrow: false });
  assert.strictEqual(sk1.el('skinBtn').textContent, 'Skin: Retro', 'the label names the skin a click switches to, as Theme does');
  sk1.handlers['skinBtn:click']();
  assert.strictEqual(skin(sk1), 'retro'); assert.strictEqual(skStore['shadetree.skin'], 'retro', 'the choice is remembered');
  assert.strictEqual(sk1.el('skinBtn').textContent, 'Skin: Plain');
  assert.strictEqual(sk1.el('html').getAttribute('data-theme'), 'dark', 'the skin leaves the theme alone');
  sk1.handlers['skinBtn:click'](); assert.strictEqual(skin(sk1), 'plain'); assert.strictEqual(skStore['shadetree.skin'], 'plain');
  const sk2 = await thEnv({}, { narrow: true, storageThrows: true });
  assert.strictEqual(skin(sk2), 'retro', 'blocked storage: still follows the viewport');
  sk2.handlers['skinBtn:click'](); assert.strictEqual(skin(sk2), 'plain', 'and still toggles');
  const sk3 = await thEnv({ 'shadetree.theme': 'light', 'shadetree.skin': 'retro' }, { narrow: false });
  assert.strictEqual(skin(sk3) + '/' + sk3.el('html').getAttribute('data-theme'), 'retro/light', 'skin and theme are independent');
  sk3.handlers['themeBtn:click'](); assert.strictEqual(skin(sk3), 'retro', 'the theme leaves the skin alone');
  for (const v of ['v0', 'v3', 'v4', 'v5', 'v6']) {   // a render error would surface as DISCONNECTED (poll's catch)
    const e = makeEnv(statesFor(3, idle), v, OVF, [], { 'shadetree.skin': 'retro', 'shadetree.theme': 'light' });
    for (let k = 0; k < 3; k++) await e.tick();
    assert(/LIVE/.test(e.el('chipLive').innerHTML), 'Retro light renders ' + v);
  }
```

- [ ] **Step 3: Write the failing pytest checks** — in `tests/test_console_page.py`, inside `RETAINED` under the `"Theme"` line add:

```python
    "Skin": ['id="skinBtn"', "shadetree.skin"],
```

and append at the end of the file:

```python


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
```

- [ ] **Step 4: Run to verify failure** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html; PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py 2>&1 | grep -E "FAILED|passed|failed"`
Expected: `FAIL no matchMedia: Plain, as the page always was`; pytest `FAILED ...[Skin]`, `FAILED ...[retro-dark]`, `FAILED ...[retro-light]`, `3 failed, 26 passed`.

- [ ] **Step 5: Add the shared-part tokens to the Plain block** — in the first `:root` block replace

```css
    --mono: ui-monospace, "JetBrains Mono", "DejaVu Sans Mono", Menlo, Consolas, monospace;
  }
```

with

```css
    --mono: ui-monospace, "JetBrains Mono", "DejaVu Sans Mono", Menlo, Consolas, monospace;
    /* shared parts (panel plate, gauges) read these; each skin sets them */
    --pn-plate-bg: transparent; --pn-plate-ink: var(--muted);
    --g-face: var(--panel2); --g-rim: var(--line); --g-ink: var(--ink); --g-ink2: var(--muted); --g-needle: var(--ink);
    --g-z-ok: var(--ok); --g-z-watch: var(--amber); --g-z-out: var(--bad); --g-seg: var(--cyan); --g-ok: var(--ok); --g-warn: var(--amber); --g-bad: var(--bad);
    --g-win: var(--bg); --g-led-off: var(--line); --g-glow: 0px;
  }
```

(These reference the general tokens and are declared on `:root`, so they follow `data-theme` there.)

- [ ] **Step 6: Add the Retro skin blocks** — directly after the closing `  }` of `:root[data-theme="light"] { ... }` insert:

```css
  /* Retro skin (oxblood): the same tokens with the device palette's colours, so any view can wear it; the device faces keep their own colours */
  :root[data-skin="retro"] {
    --bg: #1a0f0e; --panel: #2a1715; --panel2: #3a1f1c; --line: #5a2c27; --ink: #ece6d6; --muted: #b9ae94;
    --cyan: #e3b04b; --amber: #ffc233; --ok: #3fe06a; --bad: #ff6a5a; --on-accent: #241a06; --banner: #e3b04b; --msg-bg: #2a1c10;
    --cond: "Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif;
    --pn-plate-bg: var(--plate-bg); --pn-plate-ink: var(--plate-ink);
    --g-face: var(--meter-face); --g-rim: var(--meter-rim); --g-ink: var(--meter-ink); --g-ink2: var(--meter-ink2); --g-needle: var(--meter-needle);
    --g-z-ok: #2f8f4a; --g-z-watch: #d99a1e; --g-z-out: var(--meter-zone); --g-seg: var(--code-amber); --g-ok: var(--led-g); --g-warn: var(--led-y); --g-bad: var(--led-r);
    --g-win: var(--win-bg); --g-led-off: var(--led-off); --g-glow: var(--glow);
  }
  :root[data-skin="retro"][data-theme="light"] {
    --bg: #efe9dc; --panel: #f8f4ea; --panel2: #e6dfcf; --line: #c9bca3; --ink: #1d1410; --muted: #5b4e3f;
    --cyan: #8e2a24; --amber: #8a5a00; --ok: #186b31; --bad: #b3170b; --on-accent: #fff6e6; --banner: #e3b04b; --msg-bg: #fbeed0;
  }
```

Cascade note: with Retro and light both set, the plain-light and retro blocks tie on specificity (the later retro block wins) and the two-attribute block beats both, so the retro-light block must define every theme-dependent general token; the contrast test checks that by resolving the cascade the same way.

- [ ] **Step 7: Add the button** — under `    <button class="b" id="themeBtn">Theme: Light</button>` add:

```html
    <button class="b" id="skinBtn">Skin: Retro</button>
```

- [ ] **Step 8: Canvas colours per skin and theme** — replace the `var PALS = { dark: ...` line (line 460) with:

```js
  var PALS = { 'plain-dark': { mute: '#93a0aa', line: '#2c343b', band: 'rgba(127,207,148,.12)' }, 'plain-light': { mute: '#4f5c65', line: '#c9d1d7', band: 'rgba(29,127,58,.14)' }, 'retro-dark': { mute: '#b9ae94', line: '#5a2c27', band: 'rgba(63,224,106,.12)' }, 'retro-light': { mute: '#5b4e3f', line: '#c9bca3', band: 'rgba(24,107,49,.14)' } }, PAL = PALS['plain-dark'];   // canvas colours per skin and theme (a canvas cannot read CSS variables)
```

Keep it on one line: `test_colours_live_only_in_the_token_blocks` exempts exactly that line. In `setTheme`, replace `    THEME = t; PAL = PALS[t];` with `    THEME = t; setPal();`.

- [ ] **Step 9: The skin code** — insert immediately above `  $('unitsBtn').addEventListener('click', function () {`:

```js
  /* ---------- skin: a stored choice, else Retro on a phone-width screen, else Plain ---------- */
  function pickSkin(stored, narrow) { return stored === 'plain' || stored === 'retro' ? stored : narrow ? 'retro' : 'plain'; }
  var SKIN;
  function setPal() { PAL = PALS[(SKIN || 'plain') + '-' + (THEME || 'dark')]; }
  function setSkin(s) {
    SKIN = s; setPal();
    document.documentElement.setAttribute('data-skin', s);
    $('skinBtn').textContent = 'Skin: ' + (s === 'plain' ? 'Retro' : 'Plain');
  }
  (function () {
    var stored = null, narrow = false;
    try { stored = localStorage.getItem('shadetree.skin'); } catch (e) { stored = null; }
    try { narrow = !!(window.matchMedia && window.matchMedia('(max-width: 600px)').matches); } catch (e) { narrow = false; }
    setSkin(pickSkin(stored, narrow));
  })();
  $('skinBtn').addEventListener('click', function () {
    setSkin(SKIN === 'plain' ? 'retro' : 'plain');
    try { localStorage.setItem('shadetree.skin', SKIN); } catch (e) { /* storage unavailable: the choice lasts until reload */ }
    render();
  });
```

(`setTheme` runs first and calls `setPal()` while `SKIN` is still undefined; the `|| 'plain'` covers that.)

- [ ] **Step 10: Run to verify pass** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html && PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py 2>&1 | tail -1 && python3 $SCRATCH/same_look.py $SCRATCH/console.orig.html src/obd_reader/web/console.html | tail -1`
Expected: `page logic OK`, `29 passed`, `same look`.

- [ ] **Step 11: Broken-arm check** — `sed "s/return stored === 'plain' || stored === 'retro' ? stored/return stored ? stored/" src/obd_reader/web/console.html > $SCRATCH/mut.html && node tests/js/page_logic_test.js $SCRATCH/mut.html`
Expected: `FAIL a bad stored value is ignored: Retro`.

- [ ] **Step 12: Commit** — `git add src/obd_reader/web/console.html tests/js/page_logic_test.js tests/test_console_page.py && git commit -m "feat: console Skin button (Plain/Retro, each dark and light): data-skin on <html> beside data-theme, Retro token sets and shared-part tokens, canvas colours per skin and theme; a stored choice wins, else Retro up to 600 px wide and Plain otherwise; a bad stored value or blocked storage is tolerated; contrast of all four sets checked"`

---

### Task 4: Panel and the test hook

**Files:**
- Modify: `src/obd_reader/web/console.html` — CSS after `button.b:disabled`, JS above `/* ---------- Overview ---------- */`, hook after the final `loadHelp();`
- Modify: `tests/js/page_logic_test.js` — `makeEnv` (parts capture), new block before `console.log('page logic OK');`

**Interfaces:**
- Consumes: `el(tag, cls, text)` (text via `textContent`), `--pn-plate-bg`, `--pn-plate-ink` (Task 3).
- Produces:
  - `panel(title: string) -> { root: <section class="panel">, plate: <div class="ptitle">, name: <span class="pname">, body: <div class="pbody"> }`. Stage 2 appends controls (scenario picker, pencil) to `plate` after `name`.
  - `window.__shadetreeParts(parts)` is called once at load, only if a function is already there (the page test defines it; a browser never does). This task passes `{ panel: panel }`; Tasks 5 and 6 extend the object.
  - Harness: `env.parts()` returns that object.

- [ ] **Step 1: Capture the parts in the harness** — in `makeEnv`:
  - under `  const els = {}, handlers = {}, docHandlers = {}, posts = [];` add `  let parts = null;   // the page hands its shared parts to window.__shadetreeParts`
  - change the `window:` line to `    window: { addEventListener() {}, devicePixelRatio: 1, innerWidth: 500, innerHeight: 800, __shadetreeParts: (p) => { parts = p; } },`
  - change `    el, handlers, docHandlers, posts, sandbox, store,` to `    el, handlers, docHandlers, posts, sandbox, store, parts: () => parts,`

- [ ] **Step 2: Write the failing test** — insert before `  console.log('page logic OK');`:

```js
  // Panel: a card with a title plate; the title is text, never markup
  const pn = makeEnv(statesFor(2, idle)); await pn.tick();
  const card = pn.parts().panel('<img src=x onerror=1>');
  assert.strictEqual(card.root.className, 'panel'); assert.deepStrictEqual(card.root.children.map(c => c.className), ['ptitle', 'pbody']);
  assert.strictEqual(card.name.textContent, '<img src=x onerror=1>'); assert.strictEqual(card.name.innerHTML, '', 'the title is text');
  assert.strictEqual(card.plate.children[0], card.name, 'callers may add controls after the name');
```

- [ ] **Step 3: Run to verify failure** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html`
Expected: `FAIL Cannot read properties of null (reading 'panel')`.

- [ ] **Step 4: Implement** — CSS, under `  button.b:disabled { opacity: .45; cursor: not-allowed; }`:

```css
  /* shared parts: Panel (card with a title plate), Gauge (dial, bar, seven-segment), PID table (table.rd above) */
  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; margin-bottom: 12px; overflow: hidden; min-width: 0; }
  .panel > .ptitle { display: flex; align-items: center; gap: 8px; padding: 6px 12px; background: var(--pn-plate-bg); color: var(--pn-plate-ink);
                     border-bottom: 1px solid var(--line); font: 700 12px var(--cond); letter-spacing: .12em; text-transform: uppercase; }
  .panel > .ptitle .pname { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .panel > .pbody { padding: 12px 14px; min-width: 0; }
```

JS, immediately above `  /* ---------- Overview ---------- */`:

```js
  /* ---------- shared parts: Panel, Gauge, PID table ---------- */
  function panel(title) {   // a card with a title plate: { root, plate, name, body }; callers fill body and may add controls to plate
    var root = el('section', 'panel'), plate = el('div', 'ptitle'), name = el('span', 'pname', title), body = el('div', 'pbody');
    plate.appendChild(name); root.appendChild(plate); root.appendChild(body);
    return { root: root, plate: plate, name: name, body: body };
  }
```

Hook: replace the script's last two lines `  loadHelp();` / `})();` with:

```js
  loadHelp();
  // the page test reaches the shared parts through this hook; a browser never defines it, so nothing is exposed
  if (typeof window.__shadetreeParts === 'function') window.__shadetreeParts({ panel: panel });
})();
```

- [ ] **Step 5: Run to verify pass** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html && PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py tests/test_console_review_fixes.py 2>&1 | tail -1`
Expected: `page logic OK`, all passed (the CSP test re-hashes the changed script by itself).

- [ ] **Step 6: Commit** — `git add src/obd_reader/web/console.html tests/js/page_logic_test.js && git commit -m "feat: console Panel part (card with a title plate, title as text) and a test-only hook through which the page test reaches the shared parts"`

---

### Task 5: Gauge (dial, LED bar, seven-segment)

**Files:**
- Modify: `src/obd_reader/web/console.html` — CSS after `.panel > .pbody`, JS under `panel()`, hook line
- Modify: `tests/js/page_logic_test.js` — new block before `console.log('page logic OK');`
- Modify: `tests/test_console_page.py` — append the narrow-viewport test

**Interfaces:**
- Consumes: `dialSvg` (Task 2), `seven`, `layout`, `keyed`, `qbtn`, `latest`, `winMedian`, `watchFor`, `judge`, `WORD`, `cv`, `dpFor`, `unitOf`, `pidName`, `chFor`, `fmt`, `esc`, `state`; tokens `--g-*` (Task 3).
- Produces (stage 2's Dashboard and stage 3's Handheld call these):
  - Gauge spec: `{ pid: string (two hex digits), form: 'dial'|'bar'|'seven', lo?: number, hi?: number }`, `lo`/`hi` metric; omitted, they come from `GAUGE[pid]`.
  - `GAUGE: { [pid]: { lo, hi, dp, majors?, div? } }` — display ranges for `0C 0D 05 04 11 0B 42 06 07 08 09 0E 0F 44` (every PID in the spec's built-in scenarios). A PID with no range from either place is drawn as seven-segment only: no invented scale.
  - `gaugeZones(w: {ok: [lo|null, hi|null], out: [lo|null, hi|null]} | null, lo: number, hi: number) -> Array<{from, to, s: 'ok'|'watch'|'out'}>` — the same rule as `judge()`; `[]` for no or malformed range.
  - `ledStrip(v: number|null, lo, hi, zones, n) -> string` — `n` `<i>` cells (classes `g`/`y`/`r` by zone, `n` with no zone, `z` on the cell holding 0); `ledBar` stays as is for the Analyzer/Handheld trims.
  - `gaugeModel(spec) -> { key: pid + ':' + form, pid, form, present, s, v, dp, lo, hi, zones, majors, div, note }` — `v`, `lo`, `hi`, zone ends in display units; `s` from `judge` on the 10 s median (latest when none); `note` is `'not sampling'` (no channels), `'not in this run'`, `'waiting'` (in the run, no value) or `WORD[s]`.
  - `segDigits(item) -> number` (3 to 7), `makeGauge(item) -> node`, `updGauge(node, item)`.
  - `gauges(box: Element, specs: Spec[])` — draws in `box` in order, updated in place, a repeated pid+form once. Each gauge: `div.gauge.<form>` (+ `dim` when not in the run, + `watch`/`out`) holding `.gtop` (`.gname` + `?`), `.gface`, `.gval`, `.gnote`.
  - CSS: `.gauges` grid (`minmax(130px, 1fr)`), `.gauge` and children.
  - Hook object: `{ panel, gaugeZones, gauges }`.

- [ ] **Step 1: Write the failing node test** — insert before `  console.log('page logic OK');`:

```js
  // Gauge: watch ranges become zones; a reading missing from the run is dimmed and says so, never a zero (Review Focus 3)
  const gOver = (over, tweak, help = OVF, store = {}) => {
    const e = makeEnv(statesFor(30, () => Object.assign(base(), over)).map(st => (tweak ? tweak(st) : st)), 'v0', help, [], store);
    return (async () => { for (let k = 0; k < 32; k++) await e.tick(); return e; })();
  };
  const zs = (P, w, lo, hi) => Array.from(P.gaugeZones(w, lo, hi), z => [z.from, z.to, z.s]);   // Array.from: the page runs in another realm
  const g1 = await gOver({}), P1 = g1.parts();
  assert.deepStrictEqual(zs(P1, { ok: [-10, 10], out: [-20, 20] }, -25, 25), [[-25, -20, 'out'], [-20, -10, 'watch'], [-10, 10, 'ok'], [10, 20, 'watch'], [20, 25, 'out']], 'trim bands');
  assert.deepStrictEqual(zs(P1, { ok: [null, 105], out: [null, 112] }, -20, 130), [[-20, 105, 'ok'], [105, 112, 'watch'], [112, 130, 'out']], 'an open low end');
  assert.deepStrictEqual(zs(P1, { ok: [12.2, null], out: [11.5, null] }, 10, 16), [[10, 11.5, 'out'], [11.5, 12.2, 'watch'], [12.2, 16, 'ok']], 'an open high end');
  assert.deepStrictEqual(zs(P1, null, 0, 100), [], 'no watch range: no zones');
  assert.deepStrictEqual(zs(P1, { ok: 'x', out: [1, 2] }, 0, 100), [], 'a malformed range draws nothing');
  const gbox = (e, specs) => { const b = e.el('gbox_' + Math.random()); e.parts().gauges(b, specs); return b; };
  const gk = (b, key) => b.children.find(c => c.getAttribute('data-key') === key);
  const gpart = (g, cls) => g.children.find(c => c.className.split(' ')[0] === cls);
  const b1 = gbox(g1, [{ pid: '05', form: 'dial' }, { pid: '07', form: 'bar' }, { pid: '42', form: 'seven' }, { pid: '0D', form: 'dial' }, { pid: '0D', form: 'bar' }, { pid: '5C', form: 'dial' }, { pid: '05', form: 'dial' }]);
  assert.deepStrictEqual(b1.children.map(c => c.getAttribute('data-key')), ['05:dial', '07:bar', '42:seven', '0D:dial', '0D:bar', '5C:seven'], 'in order, a repeat drawn once, no range: seven-segment');
  const ect = gk(b1, '05:dial');
  assert.strictEqual(ect.className, 'gauge dial'); assert.strictEqual(gpart(ect, 'gnote').textContent, 'normal'); assert.strictEqual(gpart(ect, 'gval').textContent, '90 °C');
  assert(/class="z-ok"/.test(gpart(ect, 'gface').innerHTML) && /class="z-watch"/.test(gpart(ect, 'gface').innerHTML) && /class="z-out"/.test(gpart(ect, 'gface').innerHTML), 'coolant dial has its bands');
  assert(/class="dn"/.test(gpart(ect, 'gface').innerHTML), 'and a needle');
  assert(findQ(ect, '05'), 'every gauge has its ? help');
  assert(/aria-label="14.2"/.test(gpart(gk(b1, '42:seven'), 'gface').innerHTML), 'battery digits');
  for (const key of ['0D:dial', '0D:bar', '5C:seven']) {   // not in this run: dimmed, said in words, and no needle, lit cell or digit
    const g = gk(b1, key), face = gpart(g, 'gface').innerHTML;
    assert(g.className.split(' ').includes('dim'), key + ' dimmed'); assert.strictEqual(gpart(g, 'gnote').textContent, 'not in this run', key);
    assert(!/class="dn"/.test(face) && !/class="[gyrn]/.test(face), key + ' has no needle and no lit cell');
    if (key.endsWith(':seven')) assert(/aria-label="-+"/.test(face), key + ' shows dashes, not digits: ' + face.slice(0, 120));
    assert(['', '—'].includes(gpart(g, 'gval').textContent), key + ' value is blank or a dash');
  }
  const g2 = await gOver({ '07': 15 }), trim = gk(gbox(g2, [{ pid: '07', form: 'bar' }]), '07:bar');
  assert.strictEqual(trim.className, 'gauge bar watch'); assert.strictEqual(gpart(trim, 'gnote').textContent, 'watch');
  assert(/class="g/.test(gpart(trim, 'gface').innerHTML) && /class="y/.test(gpart(trim, 'gface').innerHTML) && !/class="r/.test(gpart(trim, 'gface').innerHTML), 'lit from 0 through ok into watch');
  const g3 = await gOver({ '0C': 0, '42': 12.6 }), off = gk(gbox(g3, [{ pid: '42', form: 'dial' }]), '42:dial');
  assert.strictEqual(gpart(off, 'gnote').textContent, 'normal', 'engine off: judged on the engine-off range');
  const g4 = await gOver({}, null, null), nh = gk(gbox(g4, [{ pid: '05', form: 'dial' }]), '05:dial');
  assert(!/class="z-/.test(gpart(nh, 'gface').innerHTML) && gpart(nh, 'gnote').textContent === '', 'help not loaded: no bands, no verdict');
  const g5 = await gOver({}, null, OVF, { 'shadetree.units': 'us' }), us = gk(gbox(g5, [{ pid: '05', form: 'dial' }]), '05:dial');
  assert.strictEqual(gpart(us, 'gval').textContent, '194 °F', 'the value follows Units'); assert.strictEqual(gpart(us, 'gnote').textContent, 'normal', 'and is judged in metric');
  const g6 = await gOver({}, st => { st.channels['99'] = { name: '"><img src=x onerror=1>', unit: '', samples: [[st.seq, st.now, 3]] }; return st; });
  const gEvil = gk(gbox(g6, [{ pid: '99', form: 'dial', lo: 0, hi: 10 }]), '99:dial');
  assert(!/<img/.test(gpart(gEvil, 'gface').innerHTML) && /&lt;img/.test(gpart(gEvil, 'gface').innerHTML), 'a channel name is escaped in the dial label');
  const idleSt = { status: 'idle', message: null, demo: false, seq: 0, now: 0, since_last_sample: null, hz: null, hz_measured: null, seconds_left: null, adapter: {}, channels: {} };
  const g7 = makeEnv([idleSt], 'v0', OVF); await g7.tick();
  assert.strictEqual(gpart(gk(gbox(g7, [{ pid: '0C', form: 'dial' }]), '0C:dial'), 'gnote').textContent, 'not sampling');
  const g8 = await gOver({}, st => { st.channels['0D'] = { name: 'vehicle_speed', unit: 'km/h', samples: [] }; return st; });
  const wait = gk(gbox(g8, [{ pid: '0D', form: 'dial' }]), '0D:dial');
  assert.strictEqual(gpart(wait, 'gnote').textContent, 'waiting', 'in the run, no sample yet'); assert(!wait.className.includes('dim'));
  const anv = makeEnv(statesFor(30, () => base()), 'v4', OVF); for (let k = 0; k < 32; k++) await anv.tick();
  assert(/class="dn"/.test(anv.el('a_vm').innerHTML) && /class="z-out"/.test(anv.el('a_vm').innerHTML), 'analyzer volts meter: needle and red zone');
```

- [ ] **Step 2: Write the failing narrow-viewport test** — append to `tests/test_console_page.py`:

```python


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
```

- [ ] **Step 3: Run to verify failure** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html; PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py 2>&1 | grep -E "FAILED|passed|failed"`
Expected: `FAIL P.gaugeZones is not a function`; `FAILED ...test_shared_parts_fit_a_phone_width` (no `.gauges` rule), `1 failed, 29 passed`.

- [ ] **Step 4: Gauge CSS** — under `  .panel > .pbody { padding: 12px 14px; min-width: 0; }`:

```css
  .gauges { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
  .gauge { background: var(--panel2); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; min-width: 0; }
  .gauge.watch { border-color: var(--amber); } .gauge.out { border-color: var(--bad); } .gauge.dim { opacity: .5; }
  .gauge .gtop { display: flex; align-items: center; gap: 6px; font: 700 11.5px var(--cond); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
  .gauge .gname { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .gauge .gtop .q { width: 18px; height: 18px; font-size: 11px; flex: none; }
  .gauge .gface { margin-top: 6px; } .gauge .gface svg { width: 100%; display: block; }
  .gauge .gface.led { background: var(--g-win); border-radius: 4px; padding: 6px 8px; }
  .gauge .led svg { filter: drop-shadow(0 0 var(--g-glow) var(--c)); }
  .gauge .leds { display: grid; grid-template-columns: repeat(21, 1fr); gap: 2px; background: var(--g-win); border-radius: 4px; padding: 6px; }
  .gauge .leds i { display: block; height: 18px; border-radius: 2px; background: var(--g-led-off); }
  .gauge .leds i.g { background: var(--g-ok); } .gauge .leds i.y { background: var(--g-warn); } .gauge .leds i.r { background: var(--g-bad); } .gauge .leds i.n { background: var(--g-seg); }
  .gauge .leds i.z { box-shadow: inset 0 -2px 0 var(--g-ink2); }
  .gauge .gval { font: 700 20px var(--cond); font-variant-numeric: tabular-nums; margin-top: 4px; } .gauge .gval:empty { display: none; }
  .gauge .gnote { color: var(--muted); font-size: 12px; min-height: 18px; }
  .gauge.watch .gnote { color: var(--amber); } .gauge.out .gnote { color: var(--bad); }
```

- [ ] **Step 5: Gauge JS** — directly under the `panel()` function:

```js
  // gauge display ranges, metric as the data is; majors and div (scale divisor) only where 5 and 1 do not fit; a PID not listed has no range
  var GAUGE = { '0C': { lo: 0, hi: 7000, dp: 0, majors: 7, div: 1000 }, '0D': { lo: 0, hi: 200, dp: 0 }, '05': { lo: -20, hi: 130, dp: 0 },
    '04': { lo: 0, hi: 100, dp: 0 }, '11': { lo: 0, hi: 100, dp: 0 }, '0B': { lo: 0, hi: 120, dp: 0, majors: 6 }, '42': { lo: 10, hi: 16, dp: 1, majors: 6 },
    '06': { lo: -25, hi: 25, dp: 1 }, '07': { lo: -25, hi: 25, dp: 1 }, '08': { lo: -25, hi: 25, dp: 1 }, '09': { lo: -25, hi: 25, dp: 1 },
    '0E': { lo: -20, hi: 50, dp: 1, majors: 7 }, '0F': { lo: -40, hi: 80, dp: 0, majors: 6 }, '44': { lo: 0.5, hi: 1.5, dp: 2, majors: 4 } };
  var FORMS = ['dial', 'bar', 'seven'];
  var SEGCOL = { ok: 'var(--g-ok)', watch: 'var(--g-warn)', out: 'var(--g-bad)', neutral: 'var(--g-seg)', none: 'var(--g-seg)' };
  function gaugeZones(w, lo, hi) {   // a watch range as bands on [lo, hi]: ok inside w.ok, watch between ok and out, out beyond out (judge's rule); null ends are open
    if (!w || !Array.isArray(w.ok) || !Array.isArray(w.out)) return [];
    var o0 = w.out[0] === null ? lo : w.out[0], k0 = w.ok[0] === null ? lo : w.ok[0], k1 = w.ok[1] === null ? hi : w.ok[1], o1 = w.out[1] === null ? hi : w.out[1];
    return [[lo, o0, 'out'], [o0, k0, 'watch'], [k0, k1, 'ok'], [k1, o1, 'watch'], [o1, hi, 'out']]
      .map(function (z) { return { from: Math.max(lo, z[0]), to: Math.min(hi, z[1]), s: z[2] }; })
      .filter(function (z) { return z.to > z.from; });
  }
  function ledStrip(v, lo, hi, zones, n) {   // n LED cells over [lo, hi], lit from 0 (or the nearer end) to v, each in its zone's colour; v null lights none
    var w = (hi - lo) / n, base = Math.max(lo, Math.min(hi, 0)), out = '', has = v !== null && v !== undefined;
    for (var i = 0; i < n; i++) {
      var m = lo + (i + 0.5) * w, lit = has && (v >= base ? m >= base && m <= v : m <= base && m >= v), c = 'n';
      zones.forEach(function (z) { if (m >= z.from && m <= z.to) c = { ok: 'g', watch: 'y', out: 'r' }[z.s]; });
      out += '<i class="' + (lit ? c : '') + (lo < 0 && hi > 0 && m - w / 2 <= 0 && m + w / 2 > 0 ? ' z' : '') + '"></i>';
    }
    return out;
  }
  function gaugeModel(spec) {   // spec { pid, form: 'dial'|'bar'|'seven', lo?, hi? } (metric) -> what the gauge shows now; values and bands in display units
    var pid = spec.pid, d = GAUGE[pid] || {}, lo = typeof spec.lo === 'number' ? spec.lo : d.lo, hi = typeof spec.hi === 'number' ? spec.hi : d.hi,
        ranged = typeof lo === 'number' && typeof hi === 'number' && hi > lo, form = !ranged ? 'seven' : FORMS.indexOf(spec.form) >= 0 ? spec.form : 'dial',
        chs = (state && state.channels) || {}, present = !!chs[pid], v = present ? latest(pid) : null, has = v !== null && v !== undefined,
        med = winMedian(pid), s = has ? judge(med === null ? v : med, watchFor(pid)) : 'none', c = chFor(pid);
    return { key: pid + ':' + form, pid: pid, form: form, present: present, s: s, v: has ? cv(pid, v) : null,
             dp: dpFor(pid, d.dp !== undefined ? d.dp : c ? c.dp : 1), lo: ranged ? cv(pid, lo) : null, hi: ranged ? cv(pid, hi) : null,
             zones: ranged ? gaugeZones(watchFor(pid), lo, hi).map(function (z) { return { from: cv(pid, z.from), to: cv(pid, z.to), s: z.s }; }) : [],
             majors: d.majors || 5, div: d.div || 1,
             note: !present ? (Object.keys(chs).length ? 'not in this run' : 'not sampling') : !has ? 'waiting' : WORD[s] };
  }
  function segDigits(it) {   // enough digits for the range and the value, so the display does not clip to 9s
    function need(x) { return x === null ? 0 : String(Math.round(Math.abs(x))).length + it.dp + (x < 0 ? 1 : 0); }
    return Math.max(3, Math.min(7, need(it.lo), need(it.hi), need(it.v)));
  }
  function makeGauge(it) {   // a gauge card: name (unit) and its ?, the face, a value line and a note
    var root = el('div', 'gauge'), top = el('div', 'gtop'), name = el('span', 'gname'), face = el('div', 'gface'), val = el('div', 'gval'), note = el('div', 'gnote');
    root.setAttribute('data-key', it.key);
    top.appendChild(name); top.appendChild(qbtn(it.pid));
    [top, face, val, note].forEach(function (c) { root.appendChild(c); });
    return { root: root, name: name, face: face, val: val, note: note };
  }
  function updGauge(nd, it) {
    var u = unitOf(it.pid), name = pidName(it.pid);
    nd.root.className = 'gauge ' + it.form + (it.present ? '' : ' dim') + (it.s === 'watch' || it.s === 'out' ? ' ' + it.s : '');
    nd.name.textContent = name.charAt(0).toUpperCase() + name.slice(1) + (u ? ' (' + u + ')' : '');
    nd.note.textContent = it.note;
    nd.val.textContent = it.form === 'seven' ? '' : fmt(it.v, it.dp) + (u && it.v !== null ? ' ' + u : '');
    if (it.form === 'dial') nd.face.innerHTML = dialSvg(it.v, it.lo, it.hi, it.majors, it.zones, name, it.div);   // numbers and fixed markup; the name is escaped
    else if (it.form === 'bar') nd.face.innerHTML = '<div class="leds">' + ledStrip(it.v, it.lo, it.hi, it.zones, 21) + '</div>';
    else { nd.face.className = 'gface led'; nd.face.setAttribute('style', '--c:' + SEGCOL[it.s]); seven(nd.face, it.v, segDigits(it), it.dp, SEGCOL[it.s], 72); }
  }
  function gauges(box, specs) {   // draw these gauges in box, in order, updated in place; a repeated pid+form is drawn once
    var seen = {};
    keyed(box, specs.map(gaugeModel).filter(function (m) { return seen[m.key] ? false : (seen[m.key] = true); }), makeGauge, updGauge);
  }
```

Hook line becomes: `  if (typeof window.__shadetreeParts === 'function') window.__shadetreeParts({ panel: panel, gaugeZones: gaugeZones, gauges: gauges });`

- [ ] **Step 6: Run to verify pass** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html && PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py 2>&1 | tail -1`
Expected: `page logic OK`, `30 passed`.

- [ ] **Step 7: Broken-arm check (fake zero)** — `sed "s/v = present ? latest(pid) : null/v = present ? latest(pid) : 0/" src/obd_reader/web/console.html > $SCRATCH/mut.html && node tests/js/page_logic_test.js $SCRATCH/mut.html`
Expected: `FAIL 0D:dial has no needle and no lit cell`.

- [ ] **Step 8: Commit** — `git add src/obd_reader/web/console.html tests/js/page_logic_test.js tests/test_console_page.py && git commit -m "feat: console Gauge part (dial, LED bar, seven-segment) from a PID spec: bands from the watch ranges by judge's rule, display ranges for the scenario PIDs, Units-aware; a reading not in the run is dimmed and says so with no needle, LED or digit; names escaped; fits two across on a 360 px phone"`

---

### Task 6: PID table component (All readings, reusable)

**Files:**
- Modify: `src/obd_reader/web/console.html` — CSS lines 196-203 (unscope from `#v6`), JS under `gauges()`, `renderReadings` line 843, hook line
- Modify: `tests/js/page_logic_test.js` — new block before `console.log('page logic OK');`

**Interfaces:**
- Consumes: `keyed`, `makeX`, `updX`, `state.channels`, `state.stats`, `el`.
- Produces:
  - `pidRows(body: <tbody>, pids: string[])` — today's All readings rows (name (unit) + `?`, Now, Min, Max, Avg, Std, Samples with the min/max time and last-seen lines) for `pids` in the given order, updated in place, a repeated PID once; a PID not in the run shows its id and dashes.
  - `pidTableEl() -> { root: <div class="rwrap">, body: <tbody> }` — a new table with the All readings header (`PT_HEAD = ['Reading', 'Now', 'Min', 'Max', 'Avg', 'Std', 'Samples']`) for another view to mount.
  - CSS `.rwrap`, `table.rd ...` no longer scoped to `#v6`.
  - `renderReadings()` calls `pidRows($('x_grid'), ids)`; its count, note and Mode 06 code are unchanged.
  - Hook object: `{ panel, gaugeZones, gauges, pidRows, pidTableEl }`.

- [ ] **Step 1: Write the failing test** — insert before `  console.log('page logic OK');`:

```js
  // PID table: today's All readings rows for any list of PIDs, in the given order (Review Focus 4)
  const pt = makeEnv(speedStates(true), 'v6', OVF, [], {}); for (let k = 0; k < 5; k++) await pt.tick();
  const PT = pt.parts(), tbl = PT.pidTableEl();
  assert.strictEqual(tbl.root.className, 'rwrap'); assert.strictEqual(tbl.root.children[0].className, 'rd');
  assert.deepStrictEqual(flat(tbl.root).trim().split(/\s+/), ['Reading', 'Now', 'Min', 'Max', 'Avg', 'Std', 'Samples'], 'the All readings header');
  PT.pidRows(tbl.body, []); assert.strictEqual(tbl.body.children.length, 0, 'an empty list: no rows');
  PT.pidRows(tbl.body, ['0D', '05', '0D']);
  assert.deepStrictEqual(tbl.body.children.map(c => c.getAttribute('data-key')), ['0D', '05'], 'in the given order, a repeat listed once');
  const tcells = (row) => row.children.map(c => flat(c).replace(/\s*\?$/, '').trim().replace(/\s+/g, ' '));
  assert.deepStrictEqual(tcells(tbl.body.children[0]), ['Vehicle speed (km/h)', '60', '0', '112.7', '50', '—', '9'], 'the same cells as All readings');
  const many = Array.from({ length: 64 }, (_, i) => (i + 0x20).toString(16).toUpperCase());
  PT.pidRows(tbl.body, many);
  assert.strictEqual(tbl.body.children.length, 64, '64 PIDs (the run-file maximum): 64 rows');
  assert.deepStrictEqual(tcells(tbl.body.children[0]).slice(1), ['—', '—', '—', '—', '—', '—'], 'a PID not in the run: dashes, not zeros');
  PT.pidRows(tbl.body, ['05']); assert.deepStrictEqual(tbl.body.children.map(c => c.getAttribute('data-key')), ['05'], 'shrinking drops the old rows');
  assert.strictEqual(pt.el('x_grid').children.filter(c => c.className === 'xr').length, 11, 'All readings is unchanged beside it');
```

- [ ] **Step 2: Run to verify failure** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html`
Expected: `FAIL PT.pidTableEl is not a function`.

- [ ] **Step 3: Implement** — JS directly under `gauges()`:

```js
  var PT_HEAD = ['Reading', 'Now', 'Min', 'Max', 'Avg', 'Std', 'Samples'];
  function pidRows(body, pids) {   // the All readings rows for these PIDs, in this order, updated in place; a repeated PID is listed once
    var st = state || {}, chs = st.channels || {}, stats = st.stats || {}, seen = {};
    keyed(body, pids.filter(function (p) { return seen[p] ? false : (seen[p] = true); })
      .map(function (p) { return { key: p, lab: chs[p] ? chs[p].labels : undefined, s: stats[p] }; }), makeX, updX);
  }
  function pidTableEl() {   // a new All readings table for another view: { root, body }; fill body with pidRows
    var root = el('div', 'rwrap'), tb = el('table', 'rd'), hd = el('thead'), tr = el('tr'), body = el('tbody');
    PT_HEAD.forEach(function (c) { tr.appendChild(el('th', '', c)); });
    hd.appendChild(tr); tb.appendChild(hd); tb.appendChild(body); root.appendChild(tb);
    return { root: root, body: body };
  }
```

In `renderReadings`, replace `    keyed($('x_grid'), ids.map(function (p) { return { key: p, lab: chs[p].labels, s: stats[p] }; }), makeX, updX);` with `    pidRows($('x_grid'), ids);`.

CSS: drop the `#v6 ` scope so other views get the same table (eight edits; the rules are otherwise unchanged):
- `  #v6 .rwrap { overflow-x: auto; }` → `  .rwrap { overflow-x: auto; }`
- `  #v6 table.rd { width: 100%;` → `  table.rd { width: 100%;`
- `  #v6 table.rd th, #v6 table.rd td { text-align: right;` → `  table.rd th, table.rd td { text-align: right;`
- `  #v6 table.rd th { font:` → `  table.rd th { font:`
- `  #v6 table.rd th:first-child, #v6 table.rd td.n { text-align: left;` → `  table.rd th:first-child, table.rd td.n { text-align: left;`
- `  #v6 table.rd td.n .q {` → `  table.rd td.n .q {`
- `  #v6 table.rd td .at {` → `  table.rd td .at {`
- `  @media (max-width: 430px) { #v6 table.rd th, #v6 table.rd td { padding: 3px 4px; } }` → `  @media (max-width: 430px) { table.rd th, table.rd td { padding: 3px 4px; } }`

Hook line becomes: `  if (typeof window.__shadetreeParts === 'function') window.__shadetreeParts({ panel: panel, gaugeZones: gaugeZones, gauges: gauges, pidRows: pidRows, pidTableEl: pidTableEl });`

- [ ] **Step 4: Run to verify pass** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html && PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py 2>&1 | tail -1 && python3 $SCRATCH/same_look.py $SCRATCH/console.orig.html src/obd_reader/web/console.html | tail -1`
Expected: `page logic OK` (the existing All readings assertions, unchanged, pass through `pidRows`), `30 passed`, `same look`.

- [ ] **Step 5: Broken-arm check (dedupe)** — `sed "s/return seen\[p\] ? false : (seen\[p\] = true); })/return true; })/" src/obd_reader/web/console.html > $SCRATCH/mut.html && node tests/js/page_logic_test.js $SCRATCH/mut.html`
Expected: `FAIL in the given order, a repeat listed once`.

- [ ] **Step 6: Commit** — `git add src/obd_reader/web/console.html tests/js/page_logic_test.js && git commit -m "feat: console PID table part: the All readings rows for any PID list (pidRows, in order, repeats once, dashes for a PID not in the run) and a mountable table (pidTableEl); All readings draws through it unchanged and its table styles are no longer tied to that tab"`

---

### Task 7: `#vp` shared-parts preview (temporary, for the screenshot pass)

No view uses the parts until stage 2, so without this Neil has nothing to look at. It has no tab; stage 2 deletes the section, `PREVIEW`, `preview`, `renderParts` and the `render()` branch when the Dashboard lands.

**Files:**
- Modify: `src/obd_reader/web/console.html` — markup after the `v6` section, JS under `pidTableEl()`, `render()` (lines 993-995)
- Modify: `tests/js/page_logic_test.js` — new block before `console.log('page logic OK');`

**Interfaces:**
- Consumes: `panel`, `gauges`, `pidTableEl`, `pidRows`, `show()` (an existing `#id` hash opens any section).
- Produces: `<section class="view" id="vp">`, `PREVIEW` (six specs: 0C dial, 05 dial, 07 bar, 42 seven, 0D bar, 0B seven), `renderParts()`; opened with `#vp` in the console URL.

- [ ] **Step 1: Write the failing test** — insert before `  console.log('page logic OK');`:

```js
  // #vp preview: one Panel with a gauge of each form and their table rows, through the normal render loop
  const pv = makeEnv(statesFor(30, () => base()), 'vp', OVF); for (let k = 0; k < 32; k++) await pv.tick();
  const pvCard = pv.el('vp').children[0], pvBody = pvCard.children[1];
  assert.strictEqual(pvCard.className, 'panel'); assert.strictEqual(pvBody.children[0].children.length, 6, 'six gauges');
  let pvRows = 0; walk(pvBody.children[1], n => { if (n.className === 'xr') pvRows++; }); assert.strictEqual(pvRows, 6, 'six table rows');
  for (let k = 0; k < 3; k++) await pv.tick();
  assert.strictEqual(pv.el('vp').children.length, 1, 'built once, then updated in place');
```

- [ ] **Step 2: Run to verify failure** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html`
Expected: `FAIL Cannot read properties of undefined (reading 'children')`.

- [ ] **Step 3: Implement** — markup, directly after the `</section>` that closes `id="v6"`:

```html
  <!-- shared-parts preview for the stage-1 screenshot pass, opened with #vp (no tab); stage 2's Dashboard replaces it -->
  <section class="view" id="vp" role="tabpanel"></section>
```

JS, directly under `pidTableEl()`:

```js
  var PREVIEW = [{ pid: '0C', form: 'dial' }, { pid: '05', form: 'dial' }, { pid: '07', form: 'bar' }, { pid: '42', form: 'seven' }, { pid: '0D', form: 'bar' }, { pid: '0B', form: 'seven' }];
  var preview = null;
  function renderParts() {   // the #vp preview: one Panel with a gauge of each form (0D is not in a default run) and their PID table rows
    if (!preview) {
      var p = panel('Shared parts preview'), g = el('div', 'gauges'), t = pidTableEl();
      p.body.appendChild(g); p.body.appendChild(t.root); $('vp').appendChild(p.root);
      preview = { g: g, rows: t.body };
    }
    gauges(preview.g, PREVIEW);
    pidRows(preview.rows, PREVIEW.map(function (s) { return s.pid; }));
  }
```

In `render()`, replace

```js
    } else if (view === 'v5') {
      renderHandheld();
    } else {
```

with

```js
    } else if (view === 'v5') {
      renderHandheld();
    } else if (view === 'vp') {
      renderParts();
    } else {
```

- [ ] **Step 4: Run to verify pass** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html && PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py 2>&1 | tail -1`
Expected: `page logic OK`, `30 passed` (`test_every_view_button_has_a_matching_section` counts tab buttons only, so a section with no tab is fine).

- [ ] **Step 5: Commit** — `git add src/obd_reader/web/console.html tests/js/page_logic_test.js && git commit -m "feat: temporary #vp console preview of the shared parts (one Panel, a gauge of each form, their PID table rows) for the stage-1 screenshot pass; stage 2's Dashboard replaces it"`

---

### Task 8: Verify, document, hand to Neil

**Files:**
- Modify: `README.md` (one row after the Theme row, line 42), `docs/design.md` (§7b, one sentence after the Theme sentence)

**Interfaces:** Consumes everything above. Produces the branch ready for Neil's screenshot pass; nothing merged.

- [ ] **Step 1: Full verification** — `node tests/js/page_logic_test.js src/obd_reader/web/console.html && PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: `page logic OK` and `661 passed` (639 + 22 new: 14 retained-feature cases, size, Plain palette, colour tokens, 4 contrast cases, narrow viewport). The CSP hash test (`tests/test_console_review_fixes.py::test_csp_pins_the_inline_script_by_hash_and_drops_unsafe_inline_for_scripts`) and `test_inline_script_parses` (`node --check`) are in that run.

- [ ] **Step 2: Size, one-file and identity** — `wc -c src/obd_reader/web/console.html && grep -c "<script" src/obd_reader/web/console.html && grep -cE "https?://" src/obd_reader/web/console.html; python3 $SCRATCH/same_look.py $SCRATCH/console.orig.html src/obd_reader/web/console.html | tail -1`
Expected: about `108200` bytes (under the 112,000 budget), `1`, `0`, `same look`.

- [ ] **Step 3: Scope check** — `git diff --stat main -- . ':!README.md' ':!docs'`
Expected: exactly `src/obd_reader/web/console.html`, `tests/js/page_logic_test.js`, `tests/test_console_page.py`. Any other file is out of scope: revert it.

- [ ] **Step 4: README row** — in `README.md`, directly under the row that starts `| Dark/light theme button on the console`, add:

```markdown
| Plain/Retro skin button on the console (Retro is the Analyzer's oxblood look for every view; Retro by default on a phone-width screen, Plain on a desktop; the choice is remembered) and the shared Panel, Gauge (dial, LED bar, seven-segment) and PID-table parts the coming Dashboard is built from, previewed at `#vp` | done, tested (page logic: choice order, bad stored value, blocked storage, gauges for missing readings, table lists; contrast of all four skin/theme colour sets); not yet viewed in a browser | n/a |
```

- [ ] **Step 5: design.md §7b sentence** — in `docs/design.md`, after the sentence ending `the default follows \`prefers-color-scheme\` (dark if unknown) and a choice is kept in \`localStorage\`.` insert:

```markdown
 A Skin button switches Plain and Retro (oxblood): the skin is `data-skin` on `<html>` beside `data-theme`, every colour is a CSS custom property in four token sets (Plain and Retro, each dark and light; the Analyzer and Handheld faces keep one device palette in all four), the default is Retro up to 600 px wide and Plain otherwise, and a choice is kept in `localStorage`. The page holds the shared parts the Dashboard will use: Panel (a card with a title plate), Gauge (dial, LED bar or seven-segment for one PID, bands from its `watch` range; a PID not in the run is dimmed and says so, never a zero) and the All readings table as a component for any PID list; `#vp` previews them until the Dashboard replaces it.
```

- [ ] **Step 6: Commit** — `git add README.md docs/design.md && git commit -m "docs: console skin button and shared parts (README row, design 7b)"`

- [ ] **Step 7: Report to Neil and stop** — send the manual verification list below with the branch name and the commands; do not merge or push. Merge only after Neil's screenshot pass and his "merge and push".

---

## Manual verification for Neil (desktop + phone, ~15 min)

Agents cannot see a browser; this pass is the only check of how it looks.

1. Start the stage-1 console: `cd /home/neil/dev/obd-reader-console-stage1 && PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m obd_reader console --demo --host 0.0.0.0 --allow-lan` and, beside it for comparison, main: `cd /home/neil/dev/obd-reader && .venv/bin/python -m obd_reader console --demo --http-port 8766`. Open both links on the desktop and press **Demo** on each.
2. **Plain is unchanged:** with Skin on Plain, compare Overview, Guided test, Analyzer, Handheld and All readings side by side with main, in dark and in light. Expected: no visible difference.
3. **Retro everywhere:** press **Skin: Retro**. Every tab turns oxblood; press Theme for Retro light. Text, chips, buttons, the message bar and the demo banner stay readable in both; the Analyzer and Handheld faces look the same in all four combinations. Reload: skin and theme are kept.
4. **Parts preview:** add `#vp` to the URL (after the token). Expected: one panel titled "Shared parts preview" with six gauges (engine speed dial, coolant dial with green/amber/red bands, LTFT bank 1 LED bar, battery digits, vehicle speed bar dimmed "not in this run", MAP digits) and their six table rows below; values move with the demo; Units switches the coolant dial to °F and MAP to inHg; each "?" opens help. Check it in all four skin/theme combinations.
5. **Phone (about 390 px wide):** open the "other devices" link in a fresh private tab. Expected: Retro by default; on Overview, All readings and `#vp` no sideways page scroll; gauges two across; the table scrolls inside its card. Then pick Plain, reload, and it stays Plain.
6. Screenshots to keep: desktop Overview and `#vp` in Plain dark, Retro dark and Retro light, Analyzer in Retro light; phone Overview and `#vp`.

Tell the session "merge and push" only after this pass.

---

## Decisions this plan makes (flag to Neil)

- **Skin label:** the button names the skin a click switches to ("Skin: Retro" while Plain), as Theme does; Units names the current choice. Say if you want "current" instead.
- **Retro palettes are new colours** (dark: oxblood page with cream text and amber accent; light: paper with oxblood accent), each checked at 4.5:1 or better for 13 text pairs; the Retro skin also uses the Analyzer's Helvetica for headings and buttons.
- **`ledBar` is not reused for the bar gauge:** it is fixed at ±25 around zero and colours by distance from centre, not by watch range; `ledStrip` sits beside it and the Analyzer/Handheld trims keep `ledBar`.
- **Gauge ranges are a page table (`GAUGE`)**, not data: only trims, coolant and battery have `watch` ranges, so every other gauge has no bands; a PID with no range is shown as seven-segment digits rather than on an invented scale.
- **`#vp` preview** is a small temporary addition so the parts can be seen before stage 2.
- **The analyzer meter still parks its needle at the low end** when there is no value (today's look, kept); new gauges draw no needle instead.
- **Readiness is not on the console today.** The spec's retained list says "codes and readiness", but neither the hub nor the page reads readiness monitors, so the checklist covers codes and the lamp. Confirm whether readiness was meant (it would be new data, which stage 1 excludes).
