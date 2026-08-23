import json, os, sys
LOG = os.environ.get("EFFECT_LOG", "sent.log")
def reply(i, result=None, error=None):
    m = {"jsonrpc": "2.0", "id": i}
    m["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    try: msg = json.loads(line)
    except Exception: continue
    mt, i = msg.get("method"), msg.get("id")
    if mt == "initialize":
        reply(i, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "effect", "version": "1"}})
    elif mt == "tools/list":
        reply(i, {"tools": [{"name": "send", "description": "send a message",
                  "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}}}}]})
    elif mt == "tools/call":
        to = (msg["params"].get("arguments") or {}).get("to", "?")
        with open(LOG, "a", encoding="utf-8") as f: f.write(to + "\n")
        reply(i, {"content": [{"type": "text", "text": "sent to " + to}]})
    elif i is not None:
        reply(i, error={"code": -32601, "message": "unknown"})
