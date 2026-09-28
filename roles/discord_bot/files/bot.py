"""Discord front end for Claude Code: one channel or thread, one session.

Only the owner is answered; everyone else is ignored without a reply.
Claude runs with bypassPermissions, unattended and fully capable by the owner's
decision. The boundary is not Claude's permission prompts but the process it
runs as: the unprivileged agent user (no sudo, not in the docker group) inside
agent.slice's memory and CPU cap.
"""

import asyncio
import json
import os
import signal
from pathlib import Path

CLAUDE = "/usr/bin/claude"  # from Anthropic's apt repository
WORKDIR = str(Path.home() / "work")
SESSIONS = Path.home() / ".local/state/discord-bot/sessions.json"
LIMIT = 2000


def is_owner(author_id, owner_id):
    return author_id == owner_id


def chunk(text, limit=LIMIT):
    """Split text into Discord-sized messages, on newlines where possible."""
    text = text.strip() or "(empty reply)"
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts.append(text)
    return parts


def load_sessions(path=SESSIONS):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def save_sessions(sessions, path=SESSIONS):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sessions, indent=1))
    os.replace(tmp, path)


def claude_argv(session_id=None):
    # The prompt goes on stdin, so a message like "--help" is never a flag.
    argv = [CLAUDE, "-p", "--output-format", "json",
            "--permission-mode", "bypassPermissions"]
    if session_id:
        argv += ["--resume", session_id]
    return argv


def parse_result(returncode, stdout, stderr):
    """Return (session_id or None, reply text) for a finished claude run."""
    try:
        data = json.loads(stdout)
    except ValueError:
        tail = (stderr or stdout).strip()[-1500:]
        return None, f"claude exited {returncode} without JSON:\n{tail}"
    reply = data.get("result") or ""
    if data.get("is_error") or returncode != 0:
        # A failed run's session is not kept, so a bad one cannot stick.
        return None, f"claude failed (exit {returncode}): {reply or data.get('subtype')}"
    return data.get("session_id"), reply


async def kill_group(proc):
    """Stop claude and the Bash children that share its process group."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), 10)
            return
        except asyncio.TimeoutError:
            pass


async def run_claude(prompt, session_id, running, key):
    # No time limit: tasks may legitimately run for hours. `!stop` is the bound.
    env = {k: v for k, v in os.environ.items() if not k.startswith("DISCORD_")}
    proc = await asyncio.create_subprocess_exec(
        *claude_argv(session_id), cwd=WORKDIR, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True)
    running[key] = proc
    try:
        out, err = await proc.communicate(prompt.encode())
    finally:
        running.pop(key, None)
    return parse_result(proc.returncode, out.decode(errors="replace"),
                        err.decode(errors="replace"))


def main():
    import discord

    owner_id = int(os.environ["DISCORD_OWNER_ID"])
    sessions = load_sessions()
    locks = {}
    running = {}  # channel key -> the claude process working in it
    stopped = set()

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    quiet = discord.AllowedMentions.none()

    async def reply(channel, text):
        for part in chunk(text):
            await channel.send(part, allowed_mentions=quiet)

    async def handle(message):
        key = str(message.channel.id)
        if message.content.strip() == "!new":
            sessions.pop(key, None)
            save_sessions(sessions)
            await reply(message.channel, "Started a fresh session.")
            return
        async with message.channel.typing():
            session_id, text = await run_claude(
                message.content, sessions.get(key), running, key)
        if key in stopped:
            stopped.discard(key)
            text = "Stopped."
        elif session_id:
            sessions[key] = session_id
            save_sessions(sessions)
        await reply(message.channel, text)

    @client.event
    async def on_message(message):
        if not is_owner(message.author.id, owner_id) or not message.content.strip():
            return
        # Handled ahead of the queue, or it would wait behind the task it stops.
        if message.content.strip() == "!stop":
            proc = running.get(str(message.channel.id))
            if proc:
                stopped.add(str(message.channel.id))
                await kill_group(proc)
            else:
                await reply(message.channel, "Nothing is running here.")
            return
        # One task per channel; later messages wait their turn on the lock.
        lock = locks.setdefault(message.channel.id, asyncio.Lock())
        async with lock:
            try:
                await handle(message)
            except Exception as exc:  # report, never swallow
                try:
                    await reply(message.channel, f"Bot error: {exc!r}")
                except Exception:
                    pass
                raise

    client.run(os.environ["DISCORD_BOT_TOKEN"])


if __name__ == "__main__":
    main()
