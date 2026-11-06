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
| `vault_monitoring.yml` | `vault_beszel_agent_key`, `vault_beszel_universal_token`, `vault_dozzle_agent_certificate`, `vault_dozzle_agent_private_key` (the Dozzle agent's mTLS pair, PEM), `vault_dozzle_alert_relay_token` (the NAS alert relay's bearer token, 64 hex characters) -- copies of the NAS vault values of the same names; rotating them there means updating them here and converging both hosts |
| `vault_github_runner.yml` | `vault_github_runner_tokens`: a fine-grained PAT (`github_pat_...`) per account or organisation in `github_runner_targets`, keyed by its name (see GitHub runners) |

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
not the server container alone: a `stop` and `start` of `lorekeeper-sync`
leaves cloudflared in the old namespace and the hostname returns 502 until the
`rejoin-shared-netns` timer restarts cloudflared, within a minute. The
directory is root-only (mode 0750), hence `sudo sh -c`:

```sh
sudo sh -c "cd /srv/lorekeeper-sync && docker compose restart"
```

The same command repairs a stranded cloudflared at once. Rerunning the playbook
applies changes but leaves unchanged containers alone, so it does not.
Foundry's cloudflared shares Foundry's namespace the same way: restart that
stack with `sudo sh -c "cd /srv/foundry && docker compose restart"`.

## GitHub runners

Self-hosted Actions runners for **private** repositories only, labelled
`self-hosted, Linux, X64, golem`. Never point a public repository at them: a
fork's pull request would run its code here. Each entry in
`github_runner_targets` gets its own runner: `owner/name` registers to that
repository (a personal account has no shared pool), a bare name to a whole
organisation. Set it up once:

1. Create a fine-grained PAT per owner, at github.com > Settings > Developer
   settings > Fine-grained tokens:
   - `yonatankarp`: resource owner yonatankarp, only the repositories listed,
     repository permission *Administration: read and write*.
   - an organisation: resource owner that organisation, organisation permission
     *Self-hosted runners: read and write*. Its Default runner group must keep
     *Allow public repositories* off (Settings > Actions > Runner groups).
2. On golem, `ansible-vault create group_vars/all/vault_github_runner.yml`:

   ```yaml
   vault_github_runner_tokens:
     yonatankarp: github_pat_...
     guillotine-mods: github_pat_...
   ```

3. Converge. Then set `runs-on: [self-hosted, golem]` in the workflows that
   should use it.

Until step 2 is done every converge stops at this role, the last one, so
everything else still converges. It also stops if any organisation in the list
lets public repositories use its runners.

The PAT only mints registration tokens; a runner that is already registered
never needs it again. Taking a target out of the list leaves its runner
registered and its unit running: stop it and remove it on GitHub by hand.

Jobs run as the `runner` user, which has no sudo and is kept off the LAN, the
tailnet and Docker's networks like the agent. `docker` in a job reaches a
rootless Docker of the runner's own, whose image store under `~runner` is the
pull cache, shared by every runner and pruned of anything older than two weeks.
Everything the runners start shares one cap (`github_runner_memory_max`,
`github_runner_cpu_quota`). Runners share a uid, so one repository's job can
read another's workspace: give them only repositories you trust alike.

The machine is Debian, not GitHub's Ubuntu image: most of its preinstalled
tools are missing, and `actions/setup-python` has no Debian builds. A workflow
may need a `container:` or its own installs before it runs here.

To look at them: `sudo -u runner XDG_RUNTIME_DIR=/run/user/$(id -u runner)
systemctl --user status 'github-runner@*'`.
