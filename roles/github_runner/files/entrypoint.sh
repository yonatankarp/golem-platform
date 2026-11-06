#!/bin/bash
# Registers a runner for one job, runs it, and exits; systemd then starts a
# fresh container. RUNNER_URL and RUNNER_TOKEN (a one-hour registration token,
# never the PAT) come from the env file github-runner-token writes.
set -euo pipefail
cd /home/runner
token="$RUNNER_TOKEN"
# Kept out of the job's environment.
unset RUNNER_TOKEN
# A name of its own (the container ID): reusing one with --replace keeps the
# runner ID, and GitHub refuses it while the last container's session lingers.
./config.sh --unattended --ephemeral --name "golem-$(hostname)" --labels golem \
    --url "$RUNNER_URL" --token "$token"
exec ./run.sh
