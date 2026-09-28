import os
"""Checks for bot.py's pure logic. Run: python3 roles/discord_bot/files/test_bot.py"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bot  # noqa: E402

# Owner filtering
assert bot.is_owner(42, 42)
assert not bot.is_owner(43, 42)

# Reply chunking
assert bot.chunk("") == ["(empty reply)"]
assert bot.chunk("hi") == ["hi"]
long_line = "x" * 4500
parts = bot.chunk(long_line)
assert [len(p) for p in parts] == [2000, 2000, 500] and "".join(parts) == long_line
lines = "\n".join(["y" * 999] * 5)
parts = bot.chunk(lines)
assert all(len(p) <= 2000 for p in parts) and len(parts) == 3
assert parts[0] == "y" * 999 + "\n" + "y" * 999

# Session map persistence
with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "state/sessions.json"
    assert bot.load_sessions(path) == {}
    bot.save_sessions({"123": "abc"}, path)
    assert bot.load_sessions(path) == {"123": "abc"}

# claude argv: no prompt in argv (it goes on stdin), resume only with a session
argv = bot.claude_argv()
assert argv[1:] == ["-p", "--output-format", "json", "--permission-mode", "bypassPermissions"]
assert bot.claude_argv("abc")[-2:] == ["--resume", "abc"]

# Result parsing
assert bot.parse_result(0, '{"result": "ok", "session_id": "s1"}', "") == ("s1", "ok")
sid, text = bot.parse_result(1, '{"is_error": true, "result": "Not logged in", "session_id": "s2"}', "")
assert sid is None and "Not logged in" in text
sid, text = bot.parse_result(127, "", "boom")
assert sid is None and "boom" in text

# !stop: kill_group takes claude's backgrounded Bash children with it
import asyncio
async def _stop():
    proc = await asyncio.create_subprocess_exec(
        "sh", "-c", "sleep 300 & echo $!; wait", stdout=asyncio.subprocess.PIPE,
        start_new_session=True)
    child = int((await proc.stdout.readline()).decode())
    await asyncio.wait_for(bot.kill_group(proc), 15)
    assert proc.returncode is not None
    await asyncio.sleep(0.2)
    try:
        os.kill(child, 0)
        raise AssertionError("background child survived !stop")
    except ProcessLookupError:
        pass
asyncio.run(_stop())

print("ok")
