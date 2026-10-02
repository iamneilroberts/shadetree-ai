#!/usr/bin/env bash
# deploy-mock.sh: publish a self-contained HTML mockup to https://mock.fuxed.org/<slug>/ (public, no login).
#   deploy-mock.sh put <slug> <file.html>   publish or replace a mock
#   deploy-mock.sh delete <slug>            remove a mock
#   deploy-mock.sh list                     slugs currently published
# slug: 1-64 chars of [a-z0-9-]. Mocks are public but not listed anywhere; X-Robots-Tag keeps them out of search.
# Needs `wrangler` logged in (OAuth: Workers write is enough). Only mock files go in; never real VINs or transcripts.
set -euo pipefail
DIR="${SHADETREE_MOCKS_DIR:-$HOME/.local/share/shadetree-mocks}"
HOST="${SHADETREE_MOCKS_HOST:-mock.fuxed.org}"
die() { echo "deploy-mock: $*" >&2; exit 1; }
cmd="${1:-}"; slug="${2:-}"
slug_ok() { echo "$1" | grep -Eq '^[a-z0-9][a-z0-9-]{0,63}$' || die "invalid slug '$1': use 1-64 chars of [a-z0-9-]"; }

mkdir -p "$DIR/site"
[ -f "$DIR/site/_headers" ] || printf '/*\n  X-Robots-Tag: noindex, nofollow\n  Cache-Control: no-cache\n' > "$DIR/site/_headers"
[ -f "$DIR/site/robots.txt" ] || printf 'User-agent: *\nDisallow: /\n' > "$DIR/site/robots.txt"
[ -f "$DIR/site/index.html" ] || printf '<!doctype html><meta charset="utf-8"><title>mock</title><p>Mockups live at /&lt;name&gt;/.\n' > "$DIR/site/index.html"
cat > "$DIR/wrangler.jsonc" <<EOF
{ "name": "shadetree-mocks", "compatibility_date": "2026-09-01",
  "assets": { "directory": "./site", "html_handling": "auto-trailing-slash", "not_found_handling": "404-page" },
  "routes": [{ "pattern": "$HOST", "custom_domain": true }] }
EOF
publish() { ( cd "$DIR" && wrangler deploy --config wrangler.jsonc 2>&1 | tail -6 ); }

case "$cmd" in
  put)
    slug_ok "$slug"; file="${3:-}"; [ -f "$file" ] || die "usage: deploy-mock.sh put <slug> <file.html>"
    mkdir -p "$DIR/site/$slug"
    if grep -qi '<!doctype' "$file"; then cp "$file" "$DIR/site/$slug/index.html"
    else   # a fragment (title, style, markup, script): give it a document, charset, viewport and zero body margin
      { printf '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}</style></head><body>\n'
        cat "$file"; printf '\n</body></html>\n'; } > "$DIR/site/$slug/index.html"
    fi
    publish; echo; echo "Published: https://$HOST/$slug/" ;;
  delete)
    slug_ok "$slug"; rm -rf "${DIR:?}/site/$slug"; publish; echo; echo "Deleted: $slug" ;;
  list)
    find "$DIR/site" -mindepth 2 -maxdepth 2 -name index.html -printf '%h\n' | sed "s|$DIR/site/||" | sort ;;
  *) die "usage: deploy-mock.sh put <slug> <file.html> | delete <slug> | list" ;;
esac
