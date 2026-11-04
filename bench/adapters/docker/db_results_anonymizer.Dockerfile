# mcp-db-results-anonymizer's published image (https://github.com/dnjfr/mcp-db-results-anonymizer,
# Apache-2.0), release 1.0.1 pinned by digest. That image installs the package without its
# `mysql` extra (no pymysql), so MySQL cannot connect; docs/CONFIGURATION.md "Supported
# databases" names the extra. This adds exactly that driver, pinned. (Its SQL Server
# connector fails with any pyodbc: see the adapter.) Nothing of its source is here.
FROM dnjfr/mcp-db-results-anonymizer@sha256:8094a8fc4eeab198823ab8d1f42da7feaddde659065e0ddcf08b6933880f961c
RUN pip install --no-cache-dir pymysql==1.1.2
