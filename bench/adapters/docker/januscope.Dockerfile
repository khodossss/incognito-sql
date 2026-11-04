# JanuScope from npm (https://github.com/giancarloerra/JanuScope, AGPL-3.0-only; run, not
# copied), pinned, with the upstream database MCP servers its bundled lenses wrap, pinned
# too: Postgres MCP Pro (lens postgres-crystaldba), @benborla29/mcp-server-mysql (lens
# mysql-benborla29) and mcp-sqlite (lens sqlite-panasenco). The lenses start them with
# uvx/npx; here they are installed once, so a run fetches nothing. postgres-mcp 0.3.0 no
# longer installs from PyPI (its pin pglast==7.2.0 is gone from the index), so the base is
# its own published image of that release, and Node 22 is copied in. mcp-sqlite 0.3.2
# does not start on the MCP SDK 2 that its open range now resolves to, so the SDK is held
# below 2, as it was at its release. Nothing of any source is here.
FROM crystaldba/postgres-mcp:0.3.0@sha256:dbbd346860d29f1543e991f30f3284bf4ab5f096d049ecc3426528f20b1b6e6b
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && python -m venv /opt/sqlite \
 && /opt/sqlite/bin/pip install --no-cache-dir mcp-sqlite==0.3.2 "mcp>=1.9.2,<2" \
 && ln -s /opt/sqlite/bin/mcp-sqlite /usr/local/bin/mcp-sqlite
RUN npm install -g --omit=dev januscope@0.5.0 @benborla29/mcp-server-mysql@2.0.9 \
 && npm cache clean --force
ENTRYPOINT ["januscope"]
