# gate (https://github.com/GaaraZhu/gate, MIT): its released Linux binary, checked against
# the release's digest, in front of DBHub from npm (https://github.com/bytebase/dbhub,
# MIT), both pinned. Nothing of either source is here.
FROM node:22-trixie-slim
RUN npm install -g --omit=dev @bytebase/dbhub@1.5.0 && npm cache clean --force
ADD --checksum=sha256:42023307a3dffee44df44dea6fb461b7a11f833f6a25d96ee7f7cfd0affc367d \
    https://github.com/GaaraZhu/gate/releases/download/v0.11.6/gate-0.11.6-x86_64-unknown-linux-gnu.tar.gz \
    /tmp/gate.tar.gz
RUN mkdir /tmp/gate && tar -xzf /tmp/gate.tar.gz -C /tmp/gate \
 && install -m 0755 "$(find /tmp/gate -type f -name gate | head -n 1)" /usr/local/bin/gate \
 && rm -rf /tmp/gate /tmp/gate.tar.gz
ENTRYPOINT ["gate", "mcp", "--", "dbhub", "--transport", "stdio"]
