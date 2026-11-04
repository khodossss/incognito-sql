# keeper's release binary (https://github.com/mtch3n/keeper, MIT), pinned and checked against
# the release's SHA256SUMS as its README's "Install" does. It does not run on Windows, so it
# runs here in Linux. keeper_start.sh (ours) registers the host and the connection with our
# catalog, as its README's "Set up a connection" does, then starts `keeper mcp`.
FROM debian:bookworm-slim
ARG VERSION=0.0.7
ARG SHA256=32df5ff400296ee61e8393581aa0dabb0b290c760c97c929d31d4f2146211c7d
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL -o /tmp/k.tgz \
    "https://github.com/mtch3n/keeper/releases/download/v${VERSION}/keeper_${VERSION}_linux_amd64.tar.gz" \
 && echo "${SHA256}  /tmp/k.tgz" | sha256sum -c - \
 && tar -xzf /tmp/k.tgz -C /tmp \
 && install -m 0755 "/tmp/keeper_${VERSION}_linux_amd64/keeper" /usr/local/bin/keeper \
 && rm -rf /tmp/k.tgz /tmp/keeper_* /var/lib/apt/lists/*
COPY keeper_start.sh /usr/local/bin/keeper_start.sh
ENTRYPOINT ["sh", "/usr/local/bin/keeper_start.sh"]
