# golem-platform

Ansible for `golem`, the Lenovo beside the NAS: agents (Claude Code),
FoundryVTT and the Lorekeeper sync server.

Ansible runs **on golem itself** from a clone of this repository, because the
secrets exist only there.

```sh
ssh golem.tail4e1ae8.ts.net
cd ~/golem-platform && git pull
ansible-galaxy collection install -r requirements.yml -p .collections
ansible-playbook site.yml --check --diff
ansible-playbook site.yml
```

CI lints and syntax-checks the playbook and runs the bot's tests, with the
tooling pinned in `controller-requirements.txt`. Renovate keeps images,
collections, actions and those pins current, and automerges non-major bumps once
CI passes; merging deploys nothing until the next `git pull` on golem.

SSH is key-only, from the LAN or the tailnet. Docker-published ports bypass ufw,
so containers publish nothing except onto the tailnet address.

## Secrets

The same layout as the NAS: one encrypted vault file per service under
`group_vars/all/`, except that here they are **gitignored and live only on
golem**, encrypted with the password in `~/.config/golem-platform/vault-password`
there. Losing golem's disk loses them; every value can be re-issued from its
source.

| File | Keys |
|---|---|
| `vault_foundry.yml` | `vault_foundry_username`, `vault_foundry_password` (foundryvtt.com), `vault_foundry_admin_key` (Foundry's /setup), `vault_cloudflare_tunnel_token` (tunnel `foundry`) |
| `vault_lorekeeper_sync.yml` | `vault_lorekeeper_sync_tunnel_token` (Cloudflare tunnel `lorekeeper-sync`), `vault_lorekeeper_sync_create_key` (who may create rooms; `openssl rand -base64 48`, at least 32 characters, entered once in the Lorekeeper app the first time you create an invite link) |
| `vault_discord_bot.yml` | `vault_discord_bot_token` (Developer Portal -> Bot), `vault_discord_owner_id` (your Discord user ID, quoted) |
| `vault_monitoring.yml` | `vault_beszel_agent_key`, `vault_beszel_universal_token`, `vault_dozzle_agent_certificate`, `vault_dozzle_agent_private_key` (the Dozzle agent's mTLS pair, PEM) -- copies of the NAS vault values of the same names; rotating them there means updating them here and converging both hosts |

Create or change one on golem:

```sh
cd ~/golem-platform && ansible-vault create group_vars/all/vault_foundry.yml
ansible-vault edit group_vars/all/vault_foundry.yml
```

Each role declares its keys as required in `meta/argument_specs.yml`, so a
missing file fails that role by name rather than deploying half-configured.

## Lorekeeper sync

The sync server for Lorekeeper's shared campaigns, at
`https://lorekeeper.yonatankarp.com`, on a Cloudflare tunnel of its own. It is
not behind Cloudflare Access: the desktop apps connect directly, and the server
authenticates each room itself. Set it up once:

1. In Cloudflare Zero Trust, Networks > Tunnels > Create a tunnel, type
   cloudflared, named `lorekeeper-sync`. Copy its token (the `eyJ...` string).
2. Give the tunnel the public hostname `lorekeeper.yonatankarp.com` with service
   `http://localhost:8080`. The route lives in the dashboard, not in this
   repository.
3. On golem, generate a room-creation key with `openssl rand -base64 48`, then
   put it and the token in the vault:
   `ansible-vault create group_vars/all/vault_lorekeeper_sync.yml` with
   `vault_lorekeeper_sync_tunnel_token: eyJ...` and
   `vault_lorekeeper_sync_create_key: <the key>`. Keep the key: the Lorekeeper
   app asks for it once, the first time you create an invite link.
4. Make sure golem can pull `ghcr.io/yonatankarp/lorekeeper-sync` anonymously:
   GHCR makes a new package private, so set it to public once the first image
   is published.
5. Converge (above). Until steps 3 and 4 are done, every converge stops at this
   role.

cloudflared shares the server's network namespace, so restart the whole stack,
never the server container alone: a `stop` and `start` of `lorekeeper-sync`
leaves cloudflared in the old namespace and the hostname returns 502. The
directory is root-only (mode 0750), hence `sudo sh -c`:

```sh
sudo sh -c "cd /srv/lorekeeper-sync && docker compose restart"
```

The same command repairs a stranded cloudflared. Rerunning the playbook applies
changes but leaves unchanged containers alone, so it does not.
