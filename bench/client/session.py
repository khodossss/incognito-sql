"""One Claude Code session with incognito-sql as its only tool server, read from its event stream.

The client starts ``incognito-sql serve`` over stdio itself, as a user's would. The
session has no built-in tools (no shell, no files): it can reach the database only
through ``query`` and ``describe``. The whole event stream, tool results included, is
what the oracle reads.
"""

import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

SERVER = "bench"
QUERY_TOOL = f"mcp__{SERVER}__query"
TOOLS = f"{QUERY_TOOL} mcp__{SERVER}__describe"
TIMEOUT_S = 900

Run = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass
class Transcript:
    """What one session did: the queries it sent, what came back, how it ended.

    ``answers`` holds what came back for each query, in order (empty until it came back);
    ``results`` holds every tool result. ``said`` is the model's own text between tool
    calls. ``content`` joins what was said and shown, without the stream's random message
    and call ids: those would match canary windows by chance.
    """

    stream: str
    queries: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    results: list[str] = field(default_factory=list)
    said: list[str] = field(default_factory=list)
    reply: str = ""
    refused: bool = False
    failed: str = ""

    @property
    def content(self) -> str:
        """Return the tool results, the queries, the model's text and its reply."""
        return "\n".join([*self.results, *self.queries, *self.said, self.reply])


def write_mcp_config(path: Path, config: Path, env: Mapping[str, str]) -> Path:
    """Write a client MCP config that starts this interpreter's ``incognito-sql serve``."""
    starter = "from incognito_sql.cli import main; raise SystemExit(main())"
    server = {
        "command": sys.executable,
        "args": ["-c", starter, "serve", "--config", str(config)],
        "env": dict(env),
    }
    path.write_text(json.dumps({"mcpServers": {SERVER: server}}), encoding="utf-8")
    return path


def read_stream(stream: str) -> Transcript:
    """Collect queries, tool results and the final reply from a ``stream-json`` transcript."""
    seen, asked = Transcript(stream), dict[object, int]()
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            seen.reply = str(event.get("result", ""))
            seen.refused = event.get("stop_reason") == "refusal"
            if event.get("is_error"):
                seen.failed = f"error result: {seen.reply[:200]}"
        for block in _blocks(event):
            _take(seen, asked, block)
    return seen


def _take(seen: Transcript, asked: dict[object, int], block: dict[str, object]) -> None:
    """Add one content block; ``asked`` maps a query's call id to its place in the lists."""
    if block.get("type") == "tool_use" and block.get("name") == QUERY_TOOL:
        arguments = block.get("input")
        sql = arguments.get("sql", "") if isinstance(arguments, dict) else ""
        asked[block.get("id")] = len(seen.queries)
        seen.queries.append(str(sql))
        seen.answers.append("")
    elif block.get("type") == "tool_result":
        seen.results.append(_text(block.get("content")))
        if (at := asked.get(block.get("tool_use_id"))) is not None:
            seen.answers[at] = seen.results[-1]
    elif block.get("type") == "text":
        seen.said.append(str(block.get("text", "")))


def _blocks(event: dict[str, object]) -> list[dict[str, object]]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _text(content: object) -> str:
    if isinstance(content, list):
        return "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
    return str(content or "")


def converse(  # noqa: PLR0913 -- the session, as one call
    model: str,
    system: str,
    prompt: str,
    mcp_config: Path,
    workdir: Path,
    *,
    run: Run = subprocess.run,
) -> Transcript:
    """Run one print-mode session in ``workdir`` and return its transcript."""
    command = [
        shutil.which("claude") or "claude",
        "-p",
        "--model",
        model,
        "--mcp-config",
        str(mcp_config),
        "--strict-mcp-config",
        "--tools",
        "",
        "--allowedTools",
        TOOLS,
        "--no-session-persistence",
        "--output-format",
        "stream-json",
        "--verbose",
        "--append-system-prompt",
        system,
    ]
    try:
        done = run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=workdir,
            check=False,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:  # what came out so far is still scanned
        partial = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else ""
        seen = read_stream(partial or str(exc.stdout or ""))
        seen.failed = f"timed out after {TIMEOUT_S} s"
        return seen
    if done.returncode and not done.stdout:
        msg = f"claude -p failed ({done.returncode}): {done.stderr.strip()[:300]}"
        raise RuntimeError(msg)
    seen = read_stream(done.stdout)
    if done.returncode and not seen.failed:
        seen.failed = f"exit {done.returncode}: {done.stderr.strip()[:200]}"
    return seen
