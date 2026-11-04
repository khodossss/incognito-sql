# DataCharter from PyPI (https://github.com/datacharter/datacharter, Apache-2.0): the wheel of
# 0.44.0, checked against its digest. Nothing of its source is here. The DuckDB extensions
# its sources attach through are installed at build (its docs fetch them on first use),
# so the container reaches nothing but the database. The workspace path is its argument.
FROM python:3.12-slim-bookworm
ADD --checksum=sha256:5a95de93152807d12198a883361817ac2a508ce8924a01c937bb4548efd012c9 \
    https://files.pythonhosted.org/packages/57/0f/10d35fb586710f5e0c26c4fb30dce5087e0d6573a153112f670cdaeb256a/datacharter-0.44.0-py3-none-any.whl \
    /tmp/datacharter-0.44.0-py3-none-any.whl
RUN pip install --no-cache-dir /tmp/datacharter-0.44.0-py3-none-any.whl \
 && rm /tmp/datacharter-0.44.0-py3-none-any.whl
ENV HOME=/tmp/home
RUN mkdir -p "$HOME" && chmod 0777 "$HOME" \
 && python -c "import duckdb; c = duckdb.connect(); [c.install_extension(e) for e in ('postgres', 'mysql', 'sqlite')]; c.execute('INSTALL mssql FROM community')" \
 && chmod -R a+rwX "$HOME"
ENTRYPOINT ["datacharter", "mcp"]
