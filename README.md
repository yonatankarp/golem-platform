# golem-platform

Ansible for `golem`, the Lenovo beside the NAS: agents (Claude Code) and FoundryVTT.

```sh
ansible-galaxy collection install -r requirements.yml -p .collections
ansible-playbook site.yml --check --diff
ansible-playbook site.yml
```

SSH is key-only, from the LAN or the tailnet. Docker-published ports bypass ufw,
so containers publish nothing except onto the tailnet address.

## Secrets

`vault.yml` is encrypted with the password in
`~/.config/golem-platform/vault-password` (generated locally, never committed).
Create it from the keys in `vault.example.yml`:

```sh
ansible-vault create vault.yml
```

The two `vault_beszel_*` values are copies of the NAS vault's values of the
same names; rotating them there means updating them here.
