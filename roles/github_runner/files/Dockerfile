# GitHub's own runner image (Ubuntu, like their hosted runners), plus what it
# lacks that workflows here expect: zstd for actions/cache, fontconfig for
# Godot. Renovate follows the digest; a runner older than GitHub accepts
# updates itself at start, so a stale image costs a download, not jobs.
FROM ghcr.io/actions/actions-runner:2.338.2@sha256:759a1d94a15b05941aba5196974ff43fe15b4cbba29b694b35cbc32a1166b232

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends zstd libfontconfig1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/hostedtoolcache
COPY entrypoint.sh /usr/local/bin/github-runner-entrypoint
# The image-pruning timer skips this, so a prune between two jobs cannot take
# the image the next runner starts from.
LABEL golem.github-runner="true"
ENTRYPOINT ["/usr/local/bin/github-runner-entrypoint"]
