# dbveil from PyPI (https://github.com/mathu97/dbveil, MIT), pinned, without its optional
# NER and LLM extras. 0.2.0 imports mcp.server.fastmcp, which the MCP SDK 2 that its open
# range (mcp>=1.2) now resolves to no longer has; the SDK is held below 2, as the SDK's
# own error advises. Nothing of its source is here.
FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir dbveil==0.2.0 "mcp>=1.2,<2"
ENTRYPOINT ["veil", "up"]
