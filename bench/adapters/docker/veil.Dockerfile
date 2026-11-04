# veil from PyPI (veil-proxy, https://github.com/lemonadesaltbagel/veil, Apache-2.0), pinned,
# with the drivers of its README's extras for Postgres, MySQL and SQL Server. Nothing of its
# source is here. At start it seeds itself from the database as its README says ("veil seed
# SOURCE", "veil seed --schema DIR"), then serves "veil mcp-db" on stdio; the seed report
# (field names and counts) goes to stderr.
FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir "veil-proxy[postgres,mysql,mssql]==0.3.2"
ENV VEIL_HOME=/tmp/veil
ENTRYPOINT ["sh", "-c", "veil seed --schema /config/veil \"$VEIL_DB\" >&2 && exec veil mcp-db \"$VEIL_DB\""]
