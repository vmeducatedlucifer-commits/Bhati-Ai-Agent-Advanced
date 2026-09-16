"""Tiny OpenAI-compatible stub used to exercise the agent loop without a real provider.

Run: python tests/mock_llm.py --port 8123
Then point a provider at http://127.0.0.1:8123/v1 with any key.

It scripts a fixed sequence: plan → write a file → run a command → summarise.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

MODEL = "mock-agent-1"

SCRIPT = [
    {
        "tool": "todo_write",
        "args": {
            "todos": [
                {"id": "t1", "title": "Create hello.py", "status": "in_progress"},
                {"id": "t2", "title": "Run it", "status": "pending"},
            ]
        },
        "text": "Chalo, do steps me karte hain.",
    },
    {
        "tool": "write_file",
        "args": {"path": "hello.py", "content": "print('hello from the sandbox')\n"},
        "text": "",
    },
    {"tool": "bash", "args": {"command": "python hello.py"}, "text": ""},
    {
        "tool": "todo_write",
        "args": {
            "todos": [
                {"id": "t1", "title": "Create hello.py", "status": "completed"},
                {"id": "t2", "title": "Run it", "status": "completed"},
            ]
        },
        "text": "",
    },
    {"tool": None, "args": {}, "text": "Ho gaya — `hello.py` bana ke chala diya. Output: hello from the sandbox."},
]


def chunk(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):  # keep the test output readable
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            body = json.dumps({"data": [{"id": MODEL}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        turn = sum(1 for m in request.get("messages", []) if m.get("role") == "assistant")
        step = SCRIPT[min(turn, len(SCRIPT) - 1)]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        base = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "model": MODEL}

        for word in (step["text"] + " ").split(" "):
            if not word:
                continue
            self.wfile.write(
                chunk({**base, "choices": [{"index": 0, "delta": {"content": word + " "}}]})
            )
            self.wfile.flush()
            time.sleep(0.02)

        if step["tool"]:
            self.wfile.write(
                chunk(
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": f"call_{turn}",
                                            "type": "function",
                                            "function": {
                                                "name": step["tool"],
                                                "arguments": json.dumps(step["args"]),
                                            },
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                )
            )

        finish = "tool_calls" if step["tool"] else "stop"
        self.wfile.write(chunk({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}))
        self.wfile.write(
            chunk({**base, "choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 30}})
        )
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8123)
    args = parser.parse_args()
    print(f"mock LLM on http://127.0.0.1:{args.port}/v1 (model {MODEL})")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
