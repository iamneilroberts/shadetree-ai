# Remote access to the console (Cloudflare Tunnel + Access)

Lets a few friends open the live console from any browser without being on your network. The console stays bound to
`127.0.0.1`. Three layers: Cloudflare Access (email one-time code, only the addresses you list), the random token in
the link, and the console's `Host` and `Origin` checks. Nothing on the page can send a command to the car.

## One time (any machine with the Cloudflare API token; the token is read from `CLOUDFLARE_API_TOKEN` or `--env-file`)

```
python3 scripts/remote_access.py setup shadetree.fuxed.org --email you@example.com --email friend@example.com
python3 scripts/remote_access.py status shadetree.fuxed.org
```

`setup` creates the tunnel `shadetree`, routes the hostname to `http://127.0.0.1:8765`, adds a proxied DNS record and an
Access application with one allow policy for those emails. It is safe to run again; running it again with a different
`--email` list replaces the list.

## On the laptop (where the OBD adapter and the console run)

1. Install `cloudflared` once.
2. Put the connector token in a file only you can read. Run this where the API token is, copy its output to the laptop:
   `python3 scripts/remote_access.py token`, then on the laptop `mkdir -p ~/.config/shadetree && chmod 700 ~/.config/shadetree`, save it as `~/.config/shadetree/tunnel-token` and `chmod 600` it.
3. Start the console with the public name allowed: `shadetree-ai console --port /dev/serial/by-id/<adapter> --allow-host shadetree.fuxed.org`
4. Start the tunnel in a second terminal: `TUNNEL_TOKEN=$(cat ~/.config/shadetree/tunnel-token) cloudflared tunnel run`
5. Send a friend the `console (remote): https://shadetree.fuxed.org/?t=...` line the console printed. They enter their email on the Cloudflare page, get a code, and are in. The token changes every time the console restarts.

## Friends

```
python3 scripts/remote_access.py add shadetree.fuxed.org new.friend@example.com
python3 scripts/remote_access.py remove shadetree.fuxed.org old.friend@example.com
```

The last allowed email cannot be removed (the gate would lock everyone out). A friend who already has a session stays in
until it expires (24 h) even after removal; shorten it in the Cloudflare dashboard if that matters.

## Turn it off

Stop `cloudflared` on the laptop (the page is unreachable at once). To delete the tunnel, the DNS record and the Access
application: `python3 scripts/remote_access.py teardown shadetree.fuxed.org`.

## Things to know

- The link's token is a second secret. Anyone who passes Access and has the full link can watch live data and start or stop sampling, load replays and save runs. They cannot send anything to the car.
- If the Access application is deleted or its policy emptied, the name is open to anyone holding the token. `status` shows whether the application and the emails are in place.
- Run files can hold the partial car key (never the VIN). Uploaded replay files stay in memory only.
