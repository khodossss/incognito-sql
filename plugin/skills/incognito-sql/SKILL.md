---
name: incognito-sql
description: Set up incognito-sql, the MCP server through which an agent queries a database holding personal data without receiving the values. Use when the user asks to connect a database through incognito-sql, to try its demo, to hide personal data from the agent while it writes SQL, or to change what an incognito-sql declaration hides.
---

# Setting up incognito-sql

1. Run `uvx "incognito-sql==0.1.0" guide`. It prints the setup's steps for this version: the cases (the demo,
   the user's own database, other people's data, several projects, a change to a
   declaration in use) and, for each step, who does it, what to ask and what to run.
2. Ask the user which case is theirs, unless they already said, then walk them through
   that case's steps in order: `uvx "incognito-sql==0.1.0" guide --case <case>`.
3. Every command the guide prints as `incognito-sql …` runs as `uvx "incognito-sql==0.1.0" …`.
4. A step marked for the human is theirs: tell them what to run in their own terminal
   and wait until they say it is done.
5. After the client restarts, go on with `uvx "incognito-sql==0.1.0" guide --case <case> --from <step>`.
6. Once the server is connected, query the database only through its tools, never the
   database file or a driver of your own.

Rule: never ask the human, in the chat, for a password, a DSN that holds one, a key, a token or any value from the database. A step that needs a secret is the human's: they run `incognito-sql secret` in their own terminal, and you learn only the variable's name.
