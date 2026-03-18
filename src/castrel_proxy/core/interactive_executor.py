"""
Interactive command executor for local shell sessions.

This module manages long-lived subprocess sessions and supports:
- start: spawn process with stdin/stdout/stderr pipes
- input: send text to stdin
- poll: read incremental stdout/stderr chunks
- stop: terminate process
"""

import asyncio
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import get_config


@dataclass
class OutputChunk:
    seq: int
    text: str
    stream: str
    timestamp: float


@dataclass
class InteractiveSession:
    session_id: str
    command: str
    cwd: str
    process: asyncio.subprocess.Process
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    stdout_chunks: List[OutputChunk] = field(default_factory=list)
    stderr_chunks: List[OutputChunk] = field(default_factory=list)
    stdout_seq: int = 0
    stderr_seq: int = 0
    exit_code: Optional[int] = None
    error: Optional[str] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stdout_task: Optional[asyncio.Task] = None
    stderr_task: Optional[asyncio.Task] = None

    def mark_active(self):
        self.last_active_at = time.time()

    def state(self) -> str:
        if self.error:
            return "error"
        if self.exit_code is not None:
            return "exited"
        return "running"


class InteractiveCommandExecutor:
    def __init__(self, max_idle_seconds: int = 600, max_sessions: int = 3):
        self.max_idle_seconds = max_idle_seconds
        self.max_sessions = max_sessions
        self.sessions: Dict[str, InteractiveSession] = {}
        self._global_lock = asyncio.Lock()
        self._prompt_patterns = [
            re.compile(r"(?i)(password|passphrase)\s*[:：]\s*$"),
            re.compile(r"(?i)(enter|input).{0,24}(choice|option|value)\s*[:：]\s*$"),
            re.compile(r"(?i)(are you sure|continue)\s*\?\s*\[[^\]]+\]\s*$"),
            re.compile(r"(?i)\b(confirm|yes/no|y/n)\b"),
            re.compile(r"(请输入|是否继续|确认\s*\(?y/?n\)?|输入验证码)"),
        ]
        self._maybe_waiting_silence_ms = 6000
        self._load_runtime_settings()

    def _load_runtime_settings(self):
        """Load optional runtime settings from ~/.castrel/config.yaml."""
        config = get_config()
        timeout_ms = config.get_interactive_silence_timeout_ms()
        self._maybe_waiting_silence_ms = timeout_ms

        extra_patterns = config.get_interactive_prompt_patterns()
        for pattern in extra_patterns:
            try:
                self._prompt_patterns.append(re.compile(pattern))
            except re.error:
                # Ignore invalid regex to keep executor stable.
                continue

    async def _cleanup_idle_sessions(self):
        now = time.time()
        stale_ids = []
        for session_id, session in self.sessions.items():
            if session.exit_code is not None:
                # Keep exited sessions briefly for final polling.
                if now - session.last_active_at > 120:
                    stale_ids.append(session_id)
            elif now - session.last_active_at > self.max_idle_seconds:
                stale_ids.append(session_id)

        for session_id in stale_ids:
            await self.stop_session(session_id=session_id, force=True)

    async def start_session(self, command: str, cwd: Optional[str] = None) -> dict:
        async with self._global_lock:
            await self._cleanup_idle_sessions()
            active_count = sum(1 for s in self.sessions.values() if s.exit_code is None)
            if active_count >= self.max_sessions:
                raise RuntimeError(f"Too many interactive sessions (limit={self.max_sessions})")

            working_dir = os.path.expanduser(os.path.expandvars(cwd or os.getcwd()))
            session_id = f"isess-{uuid.uuid4().hex[:12]}"

            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=os.environ.copy(),
            )

            session = InteractiveSession(
                session_id=session_id,
                command=command,
                cwd=working_dir,
                process=process,
            )
            session.stdout_task = asyncio.create_task(self._read_stream(session, "stdout"))
            session.stderr_task = asyncio.create_task(self._read_stream(session, "stderr"))
            self.sessions[session_id] = session

            return {
                "session_id": session_id,
                "state": session.state(),
                "pid": process.pid,
                "command": command,
                "cwd": working_dir,
            }

    async def _read_stream(self, session: InteractiveSession, stream: str):
        reader = session.process.stdout if stream == "stdout" else session.process.stderr
        if reader is None:
            return
        try:
            while True:
                chunk = await reader.read(1024)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                async with session.lock:
                    if stream == "stdout":
                        session.stdout_seq += 1
                        session.stdout_chunks.append(
                            OutputChunk(
                                seq=session.stdout_seq,
                                text=text,
                                stream=stream,
                                timestamp=time.time(),
                            )
                        )
                        # keep memory bounded
                        if len(session.stdout_chunks) > 2000:
                            session.stdout_chunks = session.stdout_chunks[-1000:]
                    else:
                        session.stderr_seq += 1
                        session.stderr_chunks.append(
                            OutputChunk(
                                seq=session.stderr_seq,
                                text=text,
                                stream=stream,
                                timestamp=time.time(),
                            )
                        )
                        if len(session.stderr_chunks) > 2000:
                            session.stderr_chunks = session.stderr_chunks[-1000:]
                    session.mark_active()
        except Exception as exc:
            async with session.lock:
                session.error = f"read {stream} failed: {exc}"
                session.mark_active()
        finally:
            if session.exit_code is None and session.process.returncode is not None:
                session.exit_code = session.process.returncode
                session.mark_active()

    async def send_input(self, session_id: str, input_text: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"interactive session not found: {session_id}")
        if session.exit_code is not None:
            return {
                "session_id": session_id,
                "state": session.state(),
                "exit_code": session.exit_code,
                "error": "session already exited",
            }
        if session.process.stdin is None:
            raise RuntimeError("session stdin is unavailable")

        session.process.stdin.write(input_text.encode("utf-8"))
        await session.process.stdin.drain()
        session.mark_active()
        return {
            "session_id": session_id,
            "state": session.state(),
            "bytes_written": len(input_text.encode("utf-8")),
        }

    async def poll(
        self,
        session_id: str,
        last_stdout_seq: int = 0,
        last_stderr_seq: int = 0,
        wait_ms: int = 0,
        max_output_bytes: int = 65536,
    ) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"interactive session not found: {session_id}")

        # Optional short wait for additional output.
        if wait_ms > 0 and session.exit_code is None:
            await asyncio.sleep(min(wait_ms, 2000) / 1000.0)

        async with session.lock:
            stdout_items = [c for c in session.stdout_chunks if c.seq > last_stdout_seq]
            stderr_items = [c for c in session.stderr_chunks if c.seq > last_stderr_seq]

            used = 0
            stdout_text = ""
            stderr_text = ""
            max_bytes = max(1024, max_output_bytes)

            for item in stdout_items:
                size = len(item.text.encode("utf-8"))
                if used + size > max_bytes:
                    break
                stdout_text += item.text
                used += size

            for item in stderr_items:
                size = len(item.text.encode("utf-8"))
                if used + size > max_bytes:
                    break
                stderr_text += item.text
                used += size

            # Update exit code if process finished and not recorded yet.
            if session.exit_code is None and session.process.returncode is not None:
                session.exit_code = session.process.returncode

            state = session.state()
            waiting_reason = "none"
            matched_prompt = None

            # Build a small tail window for prompt detection.
            tail_text = (stdout_text + "\n" + stderr_text)[-2048:]
            last_output_ts = session.created_at
            if session.stdout_chunks:
                last_output_ts = max(last_output_ts, session.stdout_chunks[-1].timestamp)
            if session.stderr_chunks:
                last_output_ts = max(last_output_ts, session.stderr_chunks[-1].timestamp)
            silence_ms = int(max(0.0, (time.time() - last_output_ts) * 1000))

            if state == "running":
                for pattern in self._prompt_patterns:
                    if pattern.search(tail_text):
                        state = "waiting_input"
                        waiting_reason = "prompt_pattern"
                        matched_prompt = pattern.pattern
                        break
                if state == "running" and silence_ms >= self._maybe_waiting_silence_ms:
                    state = "maybe_waiting_input"
                    waiting_reason = "silence_timeout"

            session.mark_active()
            return {
                "session_id": session_id,
                "state": state,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "next_stdout_seq": session.stdout_seq,
                "next_stderr_seq": session.stderr_seq,
                "exit_code": session.exit_code,
                "error": session.error,
                "silence_ms": silence_ms,
                "waiting_reason": waiting_reason,
                "matched_prompt": matched_prompt,
            }

    async def stop_session(self, session_id: str, force: bool = False) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {
                "session_id": session_id,
                "state": "exited",
                "exit_code": None,
                "error": "session not found",
            }

        try:
            if session.exit_code is None:
                if force:
                    session.process.kill()
                else:
                    session.process.terminate()
                try:
                    await asyncio.wait_for(session.process.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    session.process.kill()
                    await session.process.wait()

            session.exit_code = session.process.returncode
            session.mark_active()
        finally:
            if session.stdout_task and not session.stdout_task.done():
                session.stdout_task.cancel()
            if session.stderr_task and not session.stderr_task.done():
                session.stderr_task.cancel()
            self.sessions.pop(session_id, None)

        return {
            "session_id": session_id,
            "state": "exited",
            "exit_code": session.exit_code,
            "error": session.error,
        }


_interactive_executor = InteractiveCommandExecutor()


def get_interactive_executor() -> InteractiveCommandExecutor:
    return _interactive_executor
