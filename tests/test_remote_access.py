import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("remote_access", Path(__file__).parent.parent / "scripts" / "remote_access.py")
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)

HOST = "shadetree.voygent.ai"


class FakeCF:
    """Just enough of the Cloudflare v4 API to run setup, status, email changes and teardown offline."""

    def __init__(self, zones=None):
        self.calls, self.tunnels, self.dns, self.apps, self.policies, self.ingress = [], [], [], [], {}, None
        self.zones = zones if zones is not None else [{"id": "z1", "name": "voygent.ai", "account": {"id": "a1"}}]
        self.n = 0

    def _id(self, p):
        self.n += 1
        return f"{p}{self.n}"

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        base = path.split("?")[0]
        if method == "GET" and base == "/zones":
            return self.zones
        if base == "/accounts/a1/cfd_tunnel":
            if method == "GET":
                return [t for t in self.tunnels if "name=" + t["name"] in path]
            t = {"id": self._id("t"), "name": body["name"]}
            self.tunnels.append(t)
            return t
        if base.startswith("/accounts/a1/cfd_tunnel/"):
            tid, _, rest = base[len("/accounts/a1/cfd_tunnel/"):].partition("/")
            if method == "PUT" and rest == "configurations":
                self.ingress = body["config"]["ingress"]
                return {}
            if method == "GET" and rest == "token":
                return "CONNECTOR-TOKEN-" + tid
            if method == "DELETE" and rest == "connections":
                return {}
            if method == "DELETE":
                self.tunnels = [t for t in self.tunnels if t["id"] != tid]
                return {}
        if base == "/zones/z1/dns_records":
            if method == "GET":
                return [d for d in self.dns if d["name"] == path.split("name=")[1]]
            d = dict(body, id=self._id("d"))
            self.dns.append(d)
            return d
        if base.startswith("/zones/z1/dns_records/"):
            did = base.rsplit("/", 1)[1]
            if method == "PATCH":
                [d.update(body) for d in self.dns if d["id"] == did]
                return {}
            self.dns = [d for d in self.dns if d["id"] != did]
            return {}
        if base == "/accounts/a1/access/apps":
            if method == "GET":
                return list(self.apps)
            a = dict(body, id=self._id("app"))
            self.apps.append(a)
            self.policies[a["id"]] = []
            return a
        if base.startswith("/accounts/a1/access/apps/"):
            aid, _, rest = base[len("/accounts/a1/access/apps/"):].partition("/")
            if rest == "" and method == "DELETE":
                self.apps = [a for a in self.apps if a["id"] != aid]
                self.policies.pop(aid, None)
                return {}
            if rest == "policies" and method == "GET":
                return list(self.policies[aid])
            if rest == "policies" and method == "POST":
                p = dict(body, id=self._id("pol"))
                self.policies[aid].append(p)
                return p
            if rest.startswith("policies/") and method == "PUT":
                pid = rest.split("/")[1]
                [p.update(body) for p in self.policies[aid] if p["id"] == pid]
                return {}
        raise AssertionError(f"unexpected call {method} {path}")


def emails(fake):
    return sorted(r["email"]["email"] for p in fake.policies[fake.apps[0]["id"]] for r in p["include"])


def test_setup_creates_the_tunnel_route_dns_and_an_email_gate():
    f = FakeCF()
    out = ra.setup(f, HOST, ["Owner@Example.com", "friend@example.org"])
    assert f.tunnels[0]["name"] == "shadetree" and out["tunnel"] == f.tunnels[0]["id"]
    assert f.ingress == [{"hostname": HOST, "service": "http://127.0.0.1:8765"}, {"service": "http_status:404"}]
    assert f.dns == [dict(type="CNAME", name=HOST, content=f"{out['tunnel']}.cfargotunnel.com", proxied=True, id=f.dns[0]["id"])]
    app = f.apps[0]
    assert app["domain"] == HOST and app["type"] == "self_hosted" and app["session_duration"] == "24h"
    assert emails(f) == ["friend@example.org", "owner@example.com"]
    assert all(p["decision"] == "allow" for p in f.policies[app["id"]])
    assert "TOKEN" not in json.dumps(out), "the connector token is never part of setup's output"


def test_setup_is_idempotent_and_updates_the_emails_instead_of_duplicating():
    f = FakeCF()
    ra.setup(f, HOST, ["a@example.com"])
    ra.setup(f, HOST, ["a@example.com", "b@example.com"])
    assert len(f.tunnels) == 1 and len(f.dns) == 1 and len(f.apps) == 1 and len(f.policies[f.apps[0]["id"]]) == 1
    assert emails(f) == ["a@example.com", "b@example.com"]


def test_bad_input_is_refused_before_any_api_call():
    for kwargs in ({"hostname": "not a host", "emails": ["a@example.com"]}, {"hostname": HOST, "emails": []},
                   {"hostname": HOST, "emails": ["nope"]}, {"hostname": HOST, "emails": ["a@example.com", "x@y"]},
                   {"hostname": HOST, "emails": ["a b@example.com"]}, {"hostname": HOST, "emails": ["a@example.com"], "port": 0}):
        f = FakeCF()
        with pytest.raises(ValueError):
            ra.setup(f, **kwargs)
        assert f.calls == [], kwargs


def test_a_hostname_outside_your_zones_is_refused_without_creating_anything():
    f = FakeCF()
    with pytest.raises(ValueError, match="zone"):
        ra.setup(f, "shadetree.example.net", ["a@example.com"])
    assert not f.tunnels and not f.apps and not f.dns


def test_adding_and_removing_friends_changes_only_the_email_list():
    f = FakeCF()
    ra.setup(f, HOST, ["a@example.com"])
    assert ra.set_emails(f, HOST, add=["B@example.com", "a@example.com"]) == ["a@example.com", "b@example.com"]
    assert emails(f) == ["a@example.com", "b@example.com"]
    assert ra.set_emails(f, HOST, remove=["A@EXAMPLE.COM"]) == ["b@example.com"]
    with pytest.raises(ValueError, match="last"):
        ra.set_emails(f, HOST, remove=["b@example.com"])
    assert emails(f) == ["b@example.com"], "the gate is never left empty"
    with pytest.raises(ValueError):
        ra.set_emails(f, HOST, add=["bad"])


def test_status_and_token_and_teardown():
    f = FakeCF()
    assert ra.status(f, HOST) == {"tunnel": None, "dns": False, "app": False, "emails": []}
    out = ra.setup(f, HOST, ["a@example.com"])
    assert ra.status(f, HOST) == {"tunnel": out["tunnel"], "dns": True, "app": True, "emails": ["a@example.com"]}
    assert ra.connector_token(f) == "CONNECTOR-TOKEN-" + out["tunnel"]
    ra.teardown(f, HOST)
    assert not f.tunnels and not f.dns and not f.apps
    assert ra.status(f, HOST)["app"] is False
    ra.teardown(f, HOST)  # nothing left: not an error


def test_api_errors_carry_cloudflares_message_and_never_the_token(monkeypatch):
    import io
    import urllib.error

    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"errors":[{"message":"no permission for access"}]}'))
    monkeypatch.setattr(ra.urllib.request, "urlopen", boom)
    api = ra.make_api("SECRET-TOKEN-VALUE")
    with pytest.raises(RuntimeError) as e:
        api("GET", "/zones")
    assert "no permission for access" in str(e.value) and "SECRET-TOKEN-VALUE" not in str(e.value)


def test_the_token_file_may_be_a_bare_token_or_a_name_equals_line(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    bare = tmp_path / "bare.env"
    bare.write_text("abc123TOKEN\n")
    named = tmp_path / "named.env"
    named.write_text("OTHER=1\nCLOUDFLARE_API_TOKEN='xyz789TOKEN'\n")
    other = tmp_path / "other.env"
    other.write_text("OTHER=1\n")
    assert ra._token(str(bare)) == "abc123TOKEN"
    assert ra._token(str(named)) == "xyz789TOKEN"
    with pytest.raises(SystemExit):
        ra._token(str(other))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "from-env")
    assert ra._token(str(bare)) == "from-env", "the environment wins"
