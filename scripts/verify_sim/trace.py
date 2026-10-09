"""Print the tool calls (Bash commands, Chrome JS heads), tool errors and the final text of one run.
Usage: trace.py <round> <run> <index>"""
import json
import os
import sys
from pathlib import Path

S = Path(os.environ.get("SIM_HOME", "/Users/taejin/Project/tj_finance/logs/verify_sim"))
d = S / "runs" / sys.argv[1] / sys.argv[2] / sys.argv[3]
for line in (d / "claude.json").read_text().splitlines():
    try:
        x = json.loads(line)
    except json.JSONDecodeError:
        continue
    if x.get("type") == "assistant":
        for c in x["message"]["content"]:
            if c.get("type") == "tool_use":
                inp = c["input"]
                arg = inp.get("command") or inp.get("text") or inp.get("query") or inp.get("file_path") or inp.get("url") or ""
                print(f"> {c['name'].replace('mcp__claude-in-chrome__', 'chrome.')}: {str(arg)[:160]}")
    elif x.get("type") == "user":
        for c in x["message"]["content"] if isinstance(x["message"]["content"], list) else []:
            if c.get("type") == "tool_result" and c.get("is_error"):
                print(f"  ! {str(c.get('content'))[:200]}")
    elif x.get("type") == "result":
        print("RESULT", x.get("num_turns"), round(x.get("total_cost_usd") or 0, 3))
        print(x.get("result", "")[:1200])
