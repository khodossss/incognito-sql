# mcp-server-conceal (https://github.com/gbrigandi/mcp-server-conceal, MIT): its released
# static Linux binary, checked against our digest of it, in front of DBHub from npm
# (https://github.com/bytebase/dbhub, MIT), both pinned. Nothing of either source is here.
# DBHub reads the connection from DSN, which the proxy passes on to the server it starts.
FROM node:22-trixie-slim
RUN npm install -g --omit=dev @bytebase/dbhub@1.5.0 && npm cache clean --force
ADD --checksum=sha256:d21b6647e84342b55aafc2304c7a03002844f95669b8a6b67394e8ed9d78f345 \
    https://github.com/gbrigandi/mcp-server-conceal/releases/download/v0.1.0/mcp-server-conceal-linux-amd64 \
    /usr/local/bin/mcp-server-conceal
RUN chmod 0755 /usr/local/bin/mcp-server-conceal
WORKDIR /audit
ENTRYPOINT ["mcp-server-conceal", "--target-command", "dbhub", \
            "--target-args=--transport stdio", "--config", "/config/conceal.toml", \
            "--log-level", "warn"]
