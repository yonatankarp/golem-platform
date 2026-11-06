# GitHub's own runner image (Ubuntu, like their hosted runners), plus what it
# lacks that workflows here expect of a hosted runner: zstd (actions/cache),
# zip, Ruby, python3-venv, the Compose plugin, and Xvfb, fluxbox and the X, GL
# and audio libraries Godot opens when it draws a window. Renovate follows both
# digests; a runner older than GitHub accepts updates itself at start, so a
# stale image costs a download, not jobs.
FROM docker/compose-bin:v5.7.0@sha256:a4de4851b16f18634f74de66f126d5de65f7c5cb5a9502d67ab83e9a96041a70 AS compose

FROM ghcr.io/actions/actions-runner:2.338.2@sha256:759a1d94a15b05941aba5196974ff43fe15b4cbba29b694b35cbc32a1166b232

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        zstd zip ruby python3-venv \
        xvfb fluxbox libgl1 libegl1 libgl1-mesa-dri libglx-mesa0 \
        libxcursor1 libxinerama1 libxrandr2 libxi6 libxkbcommon0 \
        libfontconfig1 libasound2t64 libpulse0 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/hostedtoolcache
COPY --from=compose /docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
COPY entrypoint.sh /usr/local/bin/github-runner-entrypoint
# The image-pruning timer skips this, so a prune between two jobs cannot take
# the image the next runner starts from.
LABEL golem.github-runner="true"
ENTRYPOINT ["/usr/local/bin/github-runner-entrypoint"]
