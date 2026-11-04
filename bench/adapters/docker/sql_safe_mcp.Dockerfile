# sql-safe-mcp from PyPI (https://github.com/proprock/sql-safe-mcp, MIT), pinned, plus the
# Microsoft ODBC Driver 18 its README requires for SQL Server. Nothing of its source is here.
FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
    > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir sql-safe-mcp==1.5.2
ENTRYPOINT ["sql-safe-mcp"]
