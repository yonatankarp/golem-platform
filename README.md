# golem-platform

Ansible for `golem`, the Lenovo beside the NAS: agents (Claude Code) and FoundryVTT.

```sh
ansible-galaxy collection install -r requirements.yml -p .collections
ansible-playbook site.yml --check --diff
ansible-playbook site.yml
```

SSH is key-only, from the LAN or the tailnet. Docker-published ports bypass ufw,
so containers publish nothing except onto the tailnet address.
