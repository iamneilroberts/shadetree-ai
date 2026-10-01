#!/usr/bin/env python3
"""Reach the console from a remote browser through a Cloudflare Tunnel with a Cloudflare Access email gate.

  remote_access.py setup shadetree.voygent.ai --email you@example.com --email friend@example.com
  remote_access.py add shadetree.voygent.ai friend2@example.com
  remote_access.py remove shadetree.voygent.ai friend2@example.com
  remote_access.py status shadetree.voygent.ai
  remote_access.py token            # prints the tunnel connector token: a secret, paste it on the laptop only
  remote_access.py teardown shadetree.voygent.ai

The API token comes from CLOUDFLARE_API_TOKEN or from --env-file (default ~/dev/voygent-lite/.env); it is never printed.
Every step is idempotent. The console itself stays bound to loopback: run it with `--allow-host <hostname>` and run
`cloudflared tunnel run --token <connector token>` on the same machine."""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
TUNNEL = "shadetree"
_HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def make_api(token: str):
    def api(method: str, path: str, body=None):
        req = urllib.request.Request(API + path, method=method, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                msgs = [m.get("message", "") for m in json.load(e).get("errors", [])]
            except Exception:
                msgs = []
            raise RuntimeError(f"Cloudflare {e.code} on {method} {path.split('?')[0]}: {'; '.join(msgs) or 'no details'}") from None
        if not data.get("success", True):
            raise RuntimeError(f"Cloudflare refused {method} {path.split('?')[0]}: {[m.get('message') for m in data.get('errors', [])]}")
        return data.get("result")
    return api


def _clean_host(hostname) -> str:
    if not isinstance(hostname, str) or not _HOST.fullmatch(hostname.lower()) or len(hostname) > 253:
        raise ValueError("the hostname must look like shadetree.example.com")
    return hostname.lower()


def _clean_emails(emails) -> list[str]:
    out = []
    for e in emails:
        if not isinstance(e, str) or not _EMAIL.fullmatch(e):
            raise ValueError(f"not an email address: {e!r}")
        out.append(e.lower())
    return sorted(set(out))


def _zone(api, hostname: str) -> dict:
    zones = [z for z in api("GET", "/zones?per_page=50") if hostname == z["name"] or hostname.endswith("." + z["name"])]
    if not zones:
        raise ValueError(f"no Cloudflare zone on this account covers {hostname}")
    return max(zones, key=lambda z: len(z["name"]))


def _tunnel(api, acct: str, create: bool):
    found = api("GET", f"/accounts/{acct}/cfd_tunnel?is_deleted=false&name={TUNNEL}")
    if found:
        return found[0]
    return api("POST", f"/accounts/{acct}/cfd_tunnel", {"name": TUNNEL, "config_src": "cloudflare"}) if create else None


def _app(api, acct: str, hostname: str):
    return next((a for a in api("GET", f"/accounts/{acct}/access/apps") if a.get("domain") == hostname), None)


def _emails_of(policies) -> list[str]:
    return sorted({r["email"]["email"] for p in policies for r in p.get("include", []) if "email" in r})


def _include(emails):
    return [{"email": {"email": e}} for e in emails]


def setup(api, hostname: str, emails, port: int = 8765) -> dict:
    hostname, emails = _clean_host(hostname), _clean_emails(emails)
    if not emails:
        raise ValueError("give at least one --email, or nobody can get in")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be 1-65535")
    zone = _zone(api, hostname)
    acct = zone["account"]["id"]
    tunnel = _tunnel(api, acct, create=True)
    api("PUT", f"/accounts/{acct}/cfd_tunnel/{tunnel['id']}/configurations",
        {"config": {"ingress": [{"hostname": hostname, "service": f"http://127.0.0.1:{port}"}, {"service": "http_status:404"}]}})
    record = {"type": "CNAME", "name": hostname, "content": f"{tunnel['id']}.cfargotunnel.com", "proxied": True}
    existing = api("GET", f"/zones/{zone['id']}/dns_records?name={hostname}")
    if existing:
        api("PATCH", f"/zones/{zone['id']}/dns_records/{existing[0]['id']}", record)
    else:
        api("POST", f"/zones/{zone['id']}/dns_records", record)
    app = _app(api, acct, hostname) or api("POST", f"/accounts/{acct}/access/apps", {
        "name": "shadetree console", "domain": hostname, "type": "self_hosted", "session_duration": "24h"})
    policies = api("GET", f"/accounts/{acct}/access/apps/{app['id']}/policies")
    body = {"name": "friends", "decision": "allow", "include": _include(emails), "precedence": 1}
    if policies:
        api("PUT", f"/accounts/{acct}/access/apps/{app['id']}/policies/{policies[0]['id']}", body)
    else:
        api("POST", f"/accounts/{acct}/access/apps/{app['id']}/policies", body)
    return {"hostname": hostname, "tunnel": tunnel["id"], "emails": emails}


def status(api, hostname: str) -> dict:
    hostname = _clean_host(hostname)
    zone = _zone(api, hostname)
    acct = zone["account"]["id"]
    tunnel = _tunnel(api, acct, create=False)
    app = _app(api, acct, hostname)
    emails = _emails_of(api("GET", f"/accounts/{acct}/access/apps/{app['id']}/policies")) if app else []
    return {"tunnel": tunnel["id"] if tunnel else None, "dns": bool(api("GET", f"/zones/{zone['id']}/dns_records?name={hostname}")),
            "app": bool(app), "emails": emails}


def set_emails(api, hostname: str, add=(), remove=()) -> list[str]:
    hostname, add, remove = _clean_host(hostname), _clean_emails(add), _clean_emails(remove)
    acct = _zone(api, hostname)["account"]["id"]
    app = _app(api, acct, hostname)
    if not app:
        raise ValueError("nothing is set up for this hostname yet: run setup first")
    policies = api("GET", f"/accounts/{acct}/access/apps/{app['id']}/policies")
    new = sorted((set(_emails_of(policies)) | set(add)) - set(remove))
    if not new:
        raise ValueError("cannot remove the last allowed email: nobody could get in. Add another first")
    if not policies:
        raise ValueError("the access policy is missing: run setup again")
    p = policies[0]
    api("PUT", f"/accounts/{acct}/access/apps/{app['id']}/policies/{p['id']}",
        {"name": p.get("name", "friends"), "decision": p.get("decision", "allow"), "include": _include(new), "precedence": p.get("precedence", 1)})
    return new


def connector_token(api) -> str:
    acct = api("GET", "/zones?per_page=50")[0]["account"]["id"]
    tunnel = _tunnel(api, acct, create=False)
    if not tunnel:
        raise ValueError("no tunnel yet: run setup first")
    return api("GET", f"/accounts/{acct}/cfd_tunnel/{tunnel['id']}/token")


def teardown(api, hostname: str) -> None:
    hostname = _clean_host(hostname)
    zone = _zone(api, hostname)
    acct = zone["account"]["id"]
    app = _app(api, acct, hostname)
    if app:
        api("DELETE", f"/accounts/{acct}/access/apps/{app['id']}")
    for d in api("GET", f"/zones/{zone['id']}/dns_records?name={hostname}"):
        api("DELETE", f"/zones/{zone['id']}/dns_records/{d['id']}")
    tunnel = _tunnel(api, acct, create=False)
    if tunnel:
        api("DELETE", f"/accounts/{acct}/cfd_tunnel/{tunnel['id']}/connections")
        api("DELETE", f"/accounts/{acct}/cfd_tunnel/{tunnel['id']}")


def _token(env_file: str) -> str:
    tok = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not tok:
        try:
            lines = [ln.strip() for ln in open(os.path.expanduser(env_file), encoding="utf-8") if ln.strip() and not ln.lstrip().startswith("#")]
        except OSError:
            lines = []
        for line in lines:
            if line.startswith("CLOUDFLARE_API_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not tok and len(lines) == 1 and "=" not in lines[0]:
            tok = lines[0]   # a file holding just the token
    if not tok:
        sys.exit("no CLOUDFLARE_API_TOKEN in the environment or in --env-file")
    return tok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--env-file", default="~/dev/voygent-lite/.env")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("hostname"); s.add_argument("--email", action="append", default=[]); s.add_argument("--port", type=int, default=8765)
    for name in ("status", "teardown"):
        sub.add_parser(name).add_argument("hostname")
    for name in ("add", "remove"):
        p = sub.add_parser(name)
        p.add_argument("hostname"); p.add_argument("emails", nargs="+")
    sub.add_parser("token")
    a = ap.parse_args(argv)
    api = make_api(_token(a.env_file))
    try:
        if a.cmd == "setup":
            print(json.dumps(setup(api, a.hostname, a.email, a.port), indent=2))
        elif a.cmd == "status":
            print(json.dumps(status(api, a.hostname), indent=2))
        elif a.cmd == "add":
            print("allowed:", ", ".join(set_emails(api, a.hostname, add=a.emails)))
        elif a.cmd == "remove":
            print("allowed:", ", ".join(set_emails(api, a.hostname, remove=a.emails)))
        elif a.cmd == "token":
            print(connector_token(api))
        else:
            teardown(api, a.hostname)
            print("removed")
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
