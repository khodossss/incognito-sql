# Deployment: choose a profile

The server keeps personal values away from the model. It cannot do that if the agent can
log in to the database itself. Everything below protects one thing: **the agent must not
know how to reach the database** (its password, or the file of a SQLite or DuckDB
database) **nor the value key**.

Your database does not change. The profile is how the server is installed and who holds
the secrets.

| | Convenient | Closed |
|---|---|---|
| Who starts the server | the MCP client, over stdio | a service, as its own OS user |
| Where the DSN and the key live | in the client's settings, readable by the agent | only with the service |
| What the client's settings hold | the command and the secrets | a URL and a token |
| An agent with a shell | can go around the server | reaches the database only through MCP |
| Use it for | invented or your own data, or an agent without a shell | other people's personal data |

An agent without a shell (Claude Desktop, a web chat) has nothing to go around the server
with: there the convenient profile is close to closed.

This profile is about installation. What the model may do with an identifier column inside
the server (`strict`, `balanced` or `permissive`) is the protection profile, set by
`protection` in the config: see [Which profile to choose](../README.md#which-profile-to-choose).
The two are chosen apart; for other people's personal data take the closed installation and,
on purpose, `balanced` or `strict`.

## Check where you are

Run this from the account the agent runs as, in the folder it works in, with the agent's
own install of incognito-sql (the service's copy is out of its reach):

```sh
incognito-sql check --config /srv/incognito/shop.yaml --env-file /srv/incognito/secrets.env --database /srv/incognito/shop.db
```

It only reads. It tries what an agent could do: open the secrets file, the token store next
to the config and the database file (`--database`, for SQLite or DuckDB); find the key or a
database login in its environment, in its OS keyring, or in the settings of Claude Code,
Claude Desktop or Cursor. It ends with one of:

| Verdict | Exit code | Meaning |
|---|---|---|
| `profile: closed` | 0 | every probe was refused |
| `profile: convenient` | 1 | some probe got through; one `fix:` line per hole |
| `profile: unknown` | 2 | a named path does not exist, or no path was named: nothing is proven |

"Closed" covers what was probed. Without `--database` it says so: a SQLite file outside
the service's folder would go unnoticed.

## The closed profile

1. An OS account for the service, here `incognito`. The agent's account must not be able to
   become it (no `sudo` to it, no admin rights).
2. A folder only that account (and administrators) can read: the config, a secrets file,
   and the database file if the database is SQLite or DuckDB. The token store and the audit
   log are written next to the config.
3. The secrets file, `KEY=VALUE` per line:

   ```sh
   SHOP_DSN=postgresql+psycopg://incognito_reader:...@db.example:5432/shop
   INCOGNITO_SQL_KEY=<base64 of 32 random bytes>
   INCOGNITO_SQL_MCP_TOKEN=<at least 32 random characters>
   ```

   Make the key and the token with
   `python -c "import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"`.
4. The service: `incognito-sql service --config shop.yaml --env-file secrets.env`, started
   by the OS at boot (below). It serves MCP on `http://127.0.0.1:8766/mcp` (`mcp_port`): a
   request without `Authorization: Bearer <token>` gets 401. It also serves the cards on
   `web_port`, guarded by the sign-in session (below), not by the token; if that port is
   taken, the service does not start, since whoever holds it would receive sign-in links.
   The service counts literals by the installation's window only (`literal_window_s`): an
   HTTP client can start afresh with every request, so a count of its own would hold
   nothing the window does not.
5. The client gets the URL and the token. The token only opens `query` and `describe`, so
   the agent may read it. Claude Code (`.mcp.json`) expands `${VAR}` in headers:

   ```json
   {
     "mcpServers": {
       "shop": {
         "type": "http",
         "url": "http://127.0.0.1:8766/mcp",
         "headers": { "Authorization": "Bearer ${SHOP_MCP_TOKEN}" }
       }
     }
   }
   ```

6. Run `incognito-sql check` as the agent's account (above): it must say `profile: closed`.

### Where the database is

| Database | What to close | How |
|---|---|---|
| A file on this machine (SQLite, DuckDB) | the file | keep it in the service's folder, readable only by the service |
| A server on this machine (Postgres in Docker, localhost) | the password | only the secrets file holds it; the port stays open, but without the password it is useless |
| A remote server | the password and the network | as above; if the service runs on another machine, let the database accept only that machine's address |
| A managed cloud database | the same | plus a read-only role limited to the declared tables |

When the service and the agent share a machine, the database sees one address for both:
the password is what tells them apart. Only a service on another machine also closes the
network.

A container is a boundary only if the agent's account cannot control the container
engine. Members of the `docker` group (Linux) or `docker-users` (Docker Desktop on
Windows) can `docker exec` into it and read the secrets.

### Linux

The test suite runs this setup in a container (`tests/integration/test_closed_profile.py`):
the agent's account cannot read the secrets, the database file or the token store, cannot
issue a sign-in link, gets 401 without the token, and `check` reports `closed`.

```sh
sudo useradd --system --create-home incognito
sudo install -d -o incognito -m 700 /srv/incognito
# copy shop.yaml and secrets.env (and the database file) there, then:
sudo chown -R incognito /srv/incognito && sudo chmod 600 /srv/incognito/*
```

A systemd unit, `/etc/systemd/system/incognito-sql.service`:

```ini
[Unit]
Description=incognito-sql MCP service
After=network-online.target

[Service]
User=incognito
WorkingDirectory=/srv/incognito
ExecStart=/opt/incognito-sql/bin/incognito-sql service --config shop.yaml --env-file secrets.env
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Install the package where the service account can run it (here a virtual environment in
`/opt/incognito-sql`), then `sudo systemctl enable --now incognito-sql`.

### Windows

Not yet tested end to end; the Linux setup above is. In an administrator PowerShell:

```powershell
$password = Read-Host -AsSecureString "Password for the incognito account"
New-LocalUser -Name incognito -Password $password -PasswordNeverExpires
New-Item -ItemType Directory C:\incognito
icacls C:\incognito /inheritance:r /grant:r "incognito:(OI)(CI)F" "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F"
py -3.13 -m venv C:\incognito\venv
C:\incognito\venv\Scripts\pip install "C:\path\to\incognito-sql[mcp]"
# copy shop.yaml and secrets.env (and the database file) to C:\incognito, then:
$action = New-ScheduledTaskAction -Execute C:\incognito\venv\Scripts\incognito-sql.exe -Argument "service --config C:\incognito\shop.yaml --env-file C:\incognito\secrets.env" -WorkingDirectory C:\incognito
$trigger = New-ScheduledTaskTrigger -AtStartup
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($password))
Register-ScheduledTask -TaskName incognito-sql -Action $action -Trigger $trigger -User incognito -Password $plain
Start-ScheduledTask -TaskName incognito-sql
```

If the task does not start with error 0x80070569, the account lacks the "Log on as a batch
job" right: grant it in `secpol.msc`, Local Policies, User Rights Assignment.

## Signing in to the cards

The cards show real values. In the closed profile the sign-in link is issued only by
someone who can read the service's folder: the service's account or an administrator. The
agent cannot pass a UAC prompt or `sudo`. Start the service first, so the token store
already belongs to its account.

```sh
sudo -u incognito sh -c 'cd /srv/incognito && /opt/incognito-sql/bin/incognito-sql login --config shop.yaml --env-file secrets.env --print'
```

On Windows, in an administrator PowerShell:

```powershell
C:\incognito\venv\Scripts\incognito-sql.exe login --config C:\incognito\shop.yaml --env-file C:\incognito\secrets.env --print
```

`--print` writes the one-time link (valid 5 minutes) instead of opening a browser; open it
in your own browser. The session lasts `session_ttl_s` seconds, 8 hours by default.

In the convenient profile `incognito-sql login --config shop.yaml` opens the browser
directly; an agent with a shell can do the same.

**What the sign-in does not stop.** The session is a cookie in your browser, so:

- An agent running as the same OS account as your browser can read the browser's cookies
  and your clipboard, so it can take over a card session or a printed link. Run the agent
  under another account (a separate OS user, WSL, a dev container) if that matters.
- Browsers send cookies for `127.0.0.1` to every port of it. A page an agent serves on
  another local port, if you open it, receives the session cookie. Open card links only
  from the service's port, and keep `session_ttl_s` short.

## More layers

- **Client restrictions.** Claude Code can deny its file tools a path
  (`permissions.deny: ["Read(//srv/incognito/**)"]`) and run shell commands in a sandbox
  with no network (`sandbox.enabled`). The deny rule does not stop shell commands; the
  sandbox does, but it exists on macOS, Linux and WSL2 only, not on native Windows. Use
  these on top of the closed profile, not instead of it.
- **The database login.** Give the service a read-only login limited to the declared
  tables; see [the database login is the real guard](../README.md#the-database-login-is-the-real-guard).
- **Alerts.** Most databases can log logins: an alert on any login of the service's role
  from elsewhere shows a bypass attempt.
