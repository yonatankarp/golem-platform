#!/bin/bash
# Registers a runner for one job, runs it, and exits; systemd then starts a
# fresh container. RUNNER_URL, RUNNER_TOKEN (a one-hour registration token,
# never the PAT) and RUNNER_LABELS (golem, and the job's golem-pr or golem-main)
# come from the env file the scheduler writes.
set -euo pipefail
cd /home/runner
token="$RUNNER_TOKEN"
# Kept out of the job's environment.
unset RUNNER_TOKEN
# A name of its own (the container ID): reusing one with --replace keeps the
# runner ID, and GitHub refuses it while the last container's session lingers.
./config.sh --unattended --ephemeral --name "golem-$(hostname)" --labels "${RUNNER_LABELS:-golem}" \
    --url "$RUNNER_URL" --token "$token"
exec ./run.sh
