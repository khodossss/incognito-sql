"""A fake ``stream-json`` transcript and the canaries the client tests look for."""

import json
from typing import Any

from bench.client.judge import Canaries
from bench.client.session import QUERY_TOOL

HIDDEN, DECOY, OPEN = "Zqhid4x9w", "Yrdec3k8v", "Kopen7m2t"  # no shared 5-character window
CANARIES = Canaries([HIDDEN], [DECOY], [OPEN])


def stream(*answers: str, reply: str = "done", stop: str = "end_turn") -> str:
    events: list[dict[str, Any]] = [{"type": "system", "subtype": "init"}]
    for i, answer in enumerate(answers):
        use = {
            "type": "tool_use",
            "id": f"t{i}",
            "name": QUERY_TOOL,
            "input": {"sql": f"SELECT {i}"},
        }
        events.append({"type": "assistant", "message": {"content": [use]}})
        content = [{"type": "text", "text": answer}]
        result = {"type": "tool_result", "tool_use_id": f"t{i}", "content": content}
        events.append({"type": "user", "message": {"content": [result]}})
    events.append({"type": "result", "result": reply, "stop_reason": stop})
    return "\n".join(json.dumps(e) for e in events) + "\nnot json\n"
