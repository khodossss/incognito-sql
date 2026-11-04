# dbridge-mcp from npm (https://github.com/ugurcl/dbridge-mcp, MIT): the registry tarball of
# 0.7.1, checked against its digest. Nothing of its source is here. Node >= 22.5 is its
# README's requirement (built-in node:sqlite).
FROM node:22-slim
ADD --checksum=sha256:20c5db11c613a17dbee3345c4d77a50292cd6b8cfa49795ffaf678eb197df74a \
    https://registry.npmjs.org/dbridge-mcp/-/dbridge-mcp-0.7.1.tgz /tmp/dbridge-mcp.tgz
RUN npm install -g --omit=dev /tmp/dbridge-mcp.tgz && npm cache clean --force \
 && rm /tmp/dbridge-mcp.tgz
ENTRYPOINT ["dbridge-mcp"]
