# DBHub from npm (https://github.com/bytebase/dbhub, MIT), pinned: the plain database MCP
# server the wire-level and response-level proxies are paired with. Nothing of its source
# is here. Node >= 22.5 is its README's requirement (built-in node:sqlite).
FROM node:22-slim
RUN npm install -g --omit=dev @bytebase/dbhub@1.5.0 && npm cache clean --force
ENTRYPOINT ["dbhub", "--transport", "stdio"]
