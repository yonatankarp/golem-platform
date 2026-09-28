# golem-platform

Ansible for `golem`, the Lenovo beside the NAS: agents (Claude Code) and FoundryVTT.

Ansible runs **on golem itself** from a clone of this repository, because the
secrets exist only there.

```sh
ssh golem.tail4e1ae8.ts.net
cd ~/golem-platform && git pull
ansible-galaxy collection install -r requirements.yml -p .collections
ansible-playbook site.yml --check --diff
ansible-playbook site.yml
```

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
| `vault_discord_bot.yml` | `vault_discord_bot_token` (Developer Portal -> Bot), `vault_discord_owner_id` (your Discord user ID, quoted) |
| `vault_monitoring.yml` | `vault_beszel_agent_key`, `vault_beszel_universal_token`, `vault_dozzle_agent_certificate`, `vault_dozzle_agent_private_key` (the Dozzle agent's mTLS pair, PEM) -- copies of the NAS vault values of the same names; rotating them there means updating them here and converging both hosts |

Create or change one on golem:

```sh
cd ~/golem-platform && ansible-vault create group_vars/all/vault_foundry.yml
ansible-vault edit group_vars/all/vault_foundry.yml
```

Each role declares its keys as required in `meta/argument_specs.yml`, so a
missing file fails that role by name rather than deploying half-configured.
