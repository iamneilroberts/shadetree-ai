---
name: mock
description: |
  Build a UI design mockup for shadetree-ai as ONE self-contained HTML file (several variations behind a
  view-switcher, example data only) and publish it to https://mock.fuxed.org/<slug>/. Never use Artifacts for
  mockups in this repo. Triggers on `/mock`, "mock up", "design options for", "show me alternatives".
---

# mock: build and host design variations (shadetree-ai)

Mockups never go to Artifacts here. They are single HTML files hosted on fuxed.org (public, no login, unlisted, noindex).

## Steps
1. **Interview only what you cannot infer**: what screen, how many variations, what dimension varies, light/dark.
   Start from the real console look (`src/obd_reader/web/console.html`, `docs/summaries/console-stages-1-3.md`) when mocking the console.
2. **Build** from `template.html` in this folder (view-switcher with URL-hash deep links, no dependencies).
   - One file; inline all CSS and JS; no remote fonts, scripts or images (it must render from disk and offline).
   - Scope each variation's CSS under its `#id`. Label it a mockup. Work at 400 px width.
   - Example data only, marked SIMULATED. No VINs, transcripts, plates, names or places.
   - Do not ship generic AI-default design; make deliberate colour, type and layout choices for the subject.
3. **Publish**: `.claude/skills/mock/deploy-mock.sh put <slug> /tmp/mock-<slug>.html` prints `https://mock.fuxed.org/<slug>/`.
   Same slug overwrites; `delete <slug>` removes; `list` shows what is up. Append `#v2` to deep-link a variation.
4. Give the user the URL as a fenced block. Port an approved design into the repo in a worktree, as a separate task.

## Notes
- Hosting is a Cloudflare Worker with static assets (`shadetree-mocks`) on the custom domain `mock.fuxed.org`; the deploy needs `wrangler` logged in.
- Files are staged in `~/.local/share/shadetree-mocks/site/` (outside the repo).
