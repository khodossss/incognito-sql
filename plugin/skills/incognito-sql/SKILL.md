---
name: incognito-sql
description: Set up and use incognito-sql, the MCP server through which an agent queries a database holding personal data without receiving the values. Use when the user asks to connect a database through incognito-sql, to try its demo, to query such a database, to hide personal data from the agent while it writes SQL, or to change what incognito-sql hides.
---

# incognito-sql in this project

This plugin runs the incognito-sql server in every project. Its tools do the setup:
`setup_status`, `create_demo`, `draft_declaration`, `open_cards`, then `describe` and
`query`. Nothing is installed or run in a terminal, except the password, which is the
human's. No step needs a client restart.

1. Call `setup_status` first, and again after every step. It says what is set up and the
   next step; follow it.
2. The demo: `create_demo`, then `describe` and `query` (ask who spent the most).
3. The human's database in a file (SQLite, DuckDB): `draft_declaration` with `dialect` and
   `database_file`. On a server: ask the dialect and a variable name such as SHOP_DSN; the
   human runs, in their own terminal, the `secret` command `setup_status` prints; then
   `draft_declaration` with `dialect` and `dsn_env`.
4. Go through the draft with the human, column by column, and edit
   `.incognito-sql/config.yaml` as they decide; then `setup_status`.
5. Query only through `describe` and `query`. Never open the database file or
   `.incognito-sql/.env`, never connect with a driver or a script of your own.
6. If a tool call or a command is refused or blocked, stop and tell the human what was
   refused and what they can allow. Never work around it.
7. To show the human real values, call `open_cards`: it signs them in on their own browser.
8. Other people's personal data is the closed setup, a service under another OS user,
   which this server does not run: its steps are `uvx "incognito-sql==0.1.1" guide --case closed`.

Rule: never ask the human, in the chat, for a password, a DSN that holds one, a key, a token or any value from the database. A step that needs a secret is the human's: they run `incognito-sql secret` in their own terminal, and you learn only the variable's name.
