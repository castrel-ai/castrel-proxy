"""
Interactive command executor for local shell sessions.

This module manages long-lived subprocess sessions and supports:
- start: spawn process with PTY (preferred) or PIPE (fallback)
- input: send text/raw bytes to the process
- poll: read incremental stdout/stderr chunks
- stop: terminate process
- resize: adjust PTY terminal window size
"""

import asyncio
import fcntl
import logging
import os
import pty
import re
import signal
import struct
import termios
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import get_config

logger = logging.getLogger(__name__)

# Regex to strip ANSI escape sequences for prompt detection
_ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1b      # ESC
    (?:
        \[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]  # CSI sequences
      | \][^\x07]*\x07                            # OSC sequences (terminated by BEL)
      | \][^\x1b]*\x1b\\                          # OSC sequences (terminated by ST)
      | [()][AB012]                                # Character set selection
      | \[\?[0-9;]*[hlsr]                         # DEC private modes
      | [>=]                                       # Keypad modes
      | [\x20-\x2f][\x40-\x7e]                   # 2-byte sequences
    )
    """,
    re.VERBOSE,
)


@dataclass
class PromptPattern:
    """带类型标注的提示符模式，用于分类检测不同的交互式输入类型"""
    pattern: re.Pattern
    prompt_type: str  # "password" | "confirm" | "select" | "text"


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
    use_pty: bool = False
    master_fd: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    stdout_chunks: List[OutputChunk] = field(default_factory=list)
    stderr_chunks: List[OutputChunk] = field(default_factory=list)
    stdout_seq: int = 0
    stderr_seq: int = 0
    exit_code: Optional[int] = None
    error: Optional[str] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # PTY mode uses a single read_task; PIPE mode uses stdout_task + stderr_task
    read_task: Optional[asyncio.Task] = None
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
    def __init__(self, max_idle_seconds: int = 600, max_sessions: int = 10):
        self.max_idle_seconds = max_idle_seconds
        self.max_sessions = max_sessions
        self.sessions: Dict[str, InteractiveSession] = {}
        self._global_lock = asyncio.Lock()

        # 带类型标注的提示符模式（按优先级排列，password > confirm > select > text）
        self._typed_prompt_patterns: List[PromptPattern] = [
            # ---- password 类型 ----
            PromptPattern(re.compile(r"(?i)(password|passphrase)\s*[:：]\s*$"), "password"),
            PromptPattern(re.compile(r"(?i)enter.{0,20}(token|secret|key)\s*[:：]\s*$"), "password"),
            PromptPattern(re.compile(r"(输入验证码|输入密码|输入口令)"), "password"),
            # ---- confirm 类型 ----
            PromptPattern(re.compile(r"(?i)(are you sure|continue)\s*\?\s*\[[^\]]+\]\s*$"), "confirm"),
            PromptPattern(re.compile(r"(?i)\b(yes/no|y/n)\b\s*[:：)）]?\s*$"), "confirm"),
            PromptPattern(re.compile(r"(?i)(proceed|overwrite|replace|delete)\s*\?\s*"), "confirm"),
            PromptPattern(re.compile(r"(是否继续|确认\s*\(?y/?n\)?)"), "confirm"),
            # inquirer-style toggle confirm: ○ Yes / ● No, ● Yes / ○ No
            PromptPattern(re.compile(r"[○●]\s*Yes\s*/\s*[○●]\s*No"), "confirm"),
            # broad "Yes / No" pattern (covers many TUI confirm prompts)
            PromptPattern(re.compile(r"(?i)\bYes\s*/\s*No\b"), "confirm"),
            # ---- select 类型 ----
            PromptPattern(re.compile(r"(?i)(enter|input).{0,24}(choice|option|number|selection)\s*[:：]\s*$"), "select"),
            PromptPattern(re.compile(r"(?i)(choose|select)\s*(one|an?\s+option)?\s*[:：]\s*$"), "select"),
            PromptPattern(re.compile(r"(请选择|选择.{0,10}选项)"), "select"),
            # ---- text 类型（通用兜底） ----
            PromptPattern(re.compile(r"(?i)(enter|input|type)\s+.{0,30}[:：]\s*$"), "text"),
            PromptPattern(re.compile(r"(请输入)"), "text"),
        ]

        # 保留旧的无类型列表用于兼容（仅用于检测 waiting_input 状态）
        self._prompt_patterns = [tp.pattern for tp in self._typed_prompt_patterns]

        self._maybe_waiting_silence_ms = 6000

        # 选项解析模式（用于从 stdout 中提取编号选项列表）
        self._option_patterns = [
            re.compile(r"^\s*(\d+)\)\s+(.+)$", re.MULTILINE),   # 1) option_text
            re.compile(r"^\s*(\d+)\.\s+(.+)$", re.MULTILINE),   # 1. option_text
            re.compile(r"^\s*\[(\d+)\]\s+(.+)$", re.MULTILINE), # [1] option_text
            re.compile(r"^\s*\((\d+)\)\s+(.+)$", re.MULTILINE), # (1) option_text
            re.compile(r"^\s*(\d+):\s+(.+)$", re.MULTILINE),    # 1: option_text
        ]

        self._load_runtime_settings()

    def _load_runtime_settings(self):
        """Load optional runtime settings from ~/.castrel/config.yaml."""
        config = get_config()
        timeout_ms = config.get_interactive_silence_timeout_ms()
        self._maybe_waiting_silence_ms = timeout_ms

        extra_patterns = config.get_interactive_prompt_patterns()
        for pattern in extra_patterns:
            try:
                compiled = re.compile(pattern)
                self._prompt_patterns.append(compiled)
                # 用户自定义模式默认作为 text 类型
                self._typed_prompt_patterns.append(PromptPattern(compiled, "text"))
            except re.error:
                # Ignore invalid regex to keep executor stable.
                continue

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Strip ANSI escape sequences from text for clean prompt detection."""
        return _ANSI_ESCAPE_RE.sub("", text)

    def _detect_prompt_type(self, tail_text: str) -> tuple:
        """
        检测提示符类型，返回 (prompt_type, matched_prompt) 或 (None, None)。
        按 _typed_prompt_patterns 优先级顺序匹配。
        """
        for tp in self._typed_prompt_patterns:
            if tp.pattern.search(tail_text):
                return tp.prompt_type, tp.pattern.pattern
        return None, None

    def _parse_select_options(self, tail_text: str) -> List[dict]:
        """
        从 stdout 尾部解析编号选项列表。

        支持格式:
          1) option_text    (shell select)
          1. option_text    (Python 脚本)
          [1] option_text   (安装程序)
          (1) option_text
          1: option_text
        """
        for pat in self._option_patterns:
            matches = pat.findall(tail_text)
            if len(matches) >= 2:  # 至少 2 个选项才认为是有效的选择列表
                return [
                    {"value": m[0].strip(), "label": m[1].strip()}
                    for m in matches
                ]
        return []

    @staticmethod
    def _parse_confirm_default(tail_text: str) -> Optional[str]:
        """
        从提示符中解析 confirm 类型的默认值。

        [Y/n] -> "y"  (大写 = 默认)
        [y/N] -> "n"
        (yes/no) -> None (无默认)
        """
        m = re.search(r"\[([yYnN])/([yYnN])\]", tail_text)
        if m:
            left, right = m.group(1), m.group(2)
            if left.isupper():
                return left.lower()
            if right.isupper():
                return right.lower()
        return None

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
            try:
                await asyncio.wait_for(
                    self.stop_session(session_id=session_id, force=True),
                    timeout=8.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[INTERACTIVE] Cleanup timed out for session {session_id}, "
                    f"forcing removal from registry"
                )
                # Force remove from registry even if stop_session hung
                self.sessions.pop(session_id, None)
            except Exception as e:
                logger.warning(f"[INTERACTIVE] Cleanup error for {session_id}: {e}")
                self.sessions.pop(session_id, None)

    async def start_session(self, command: str, cwd: Optional[str] = None) -> dict:
        try:
            await asyncio.wait_for(self._global_lock.acquire(), timeout=15.0)
        except asyncio.TimeoutError:
            logger.error(
                "[INTERACTIVE] Failed to acquire global lock within 15s, "
                "forcing lock release and retrying"
            )
            # Force release: create a new lock to unblock
            self._global_lock = asyncio.Lock()
            await self._global_lock.acquire()

        try:
            await self._cleanup_idle_sessions()
            active_count = sum(1 for s in self.sessions.values() if s.exit_code is None)
            if active_count >= self.max_sessions:
                raise RuntimeError(f"Too many interactive sessions (limit={self.max_sessions})")

            working_dir = os.path.expanduser(os.path.expandvars(cwd or os.getcwd()))
            session_id = f"isess-{uuid.uuid4().hex[:12]}"

            use_pty = False
            master_fd = None

            try:
                master_fd, slave_fd = pty.openpty()

                # Set terminal window size (default 80x24)
                winsize = struct.pack("HHHH", 24, 80, 0, 0)
                fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

                # Disable ECHO on slave — the frontend handles local echo,
                # PTY echo would cause double display of user input.
                attrs = termios.tcgetattr(slave_fd)
                attrs[3] &= ~termios.ECHO
                termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

                process = await asyncio.create_subprocess_shell(
                    command,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    cwd=working_dir,
                    env={**os.environ, "TERM": "xterm-256color"},
                )

                # Close slave fd — the child process has inherited it
                os.close(slave_fd)
                use_pty = True

                logger.info(
                    f"[INTERACTIVE] PTY session started: session_id={session_id}, "
                    f"command={command}, master_fd={master_fd}"
                )
            except OSError as exc:
                # Fallback to PIPE mode if PTY creation fails
                logger.warning(
                    f"[INTERACTIVE] PTY creation failed, falling back to PIPE mode: {exc}"
                )
                if master_fd is not None:
                    try:
                        os.close(master_fd)
                    except OSError:
                        pass
                    master_fd = None

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
                use_pty=use_pty,
                master_fd=master_fd,
            )

            if use_pty:
                session.read_task = asyncio.create_task(
                    self._read_pty_output(session)
                )
            else:
                session.stdout_task = asyncio.create_task(
                    self._read_stream(session, "stdout")
                )
                session.stderr_task = asyncio.create_task(
                    self._read_stream(session, "stderr")
                )

            self.sessions[session_id] = session

            return {
                "session_id": session_id,
                "state": session.state(),
                "pid": process.pid,
                "command": command,
                "cwd": working_dir,
                "use_pty": use_pty,
            }
        finally:
            self._global_lock.release()

    async def _read_pty_output(self, session: InteractiveSession):
        """Read output from PTY master fd asynchronously.

        Uses select() with a timeout to avoid indefinite blocking in the
        thread executor, which could prevent session cleanup on macOS.
        """
        import select as _select

        loop = asyncio.get_event_loop()
        master_fd = session.master_fd
        if master_fd is None:
            return

        def _read_with_timeout(fd: int, timeout: float = 1.0) -> bytes:
            """Read from fd with a timeout. Returns b'' on timeout or EOF."""
            ready, _, _ = _select.select([fd], [], [], timeout)
            if ready:
                return os.read(fd, 4096)
            return b""  # timeout, no data yet

        try:
            while True:
                try:
                    data = await loop.run_in_executor(
                        None, lambda: _read_with_timeout(master_fd)
                    )
                except OSError:
                    break
                if data == b"" and session.process.returncode is not None:
                    # Process exited and no more data
                    break
                if data == b"":
                    # Timeout with no data, but process still running
                    continue

                text = data.decode("utf-8", errors="replace")
                async with session.lock:
                    session.stdout_seq += 1
                    session.stdout_chunks.append(
                        OutputChunk(
                            seq=session.stdout_seq,
                            text=text,
                            stream="stdout",
                            timestamp=time.time(),
                        )
                    )
                    if len(session.stdout_chunks) > 2000:
                        session.stdout_chunks = session.stdout_chunks[-1000:]
                    session.mark_active()
        except asyncio.CancelledError:
            logger.debug(f"[INTERACTIVE] PTY read task cancelled: session_id={session.session_id}")
        except Exception as exc:
            async with session.lock:
                if session.exit_code is None:
                    session.error = f"read pty failed: {exc}"
                session.mark_active()
        finally:
            if session.exit_code is None and session.process.returncode is not None:
                async with session.lock:
                    session.exit_code = session.process.returncode
                    session.mark_active()

    async def _read_stream(self, session: InteractiveSession, stream: str):
        """Read output from PIPE stdout/stderr (fallback mode)."""
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

        if session.use_pty and session.master_fd is not None:
            # PTY mode: write raw bytes directly to master fd
            # Do NOT auto-append \n — the frontend/caller controls the exact payload
            payload = input_text.encode("utf-8")
            try:
                os.write(session.master_fd, payload)
            except OSError as exc:
                raise RuntimeError(f"failed to write to PTY: {exc}") from exc
        else:
            # PIPE mode (fallback): write to stdin with auto newline
            if session.process.stdin is None:
                raise RuntimeError("session stdin is unavailable")
            payload_str = input_text
            if payload_str and not payload_str.endswith("\n"):
                payload_str += "\n"
            payload = payload_str.encode("utf-8")
            session.process.stdin.write(payload)
            await session.process.stdin.drain()

        session.mark_active()
        return {
            "session_id": session_id,
            "state": session.state(),
            "bytes_written": len(payload),
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

        # Smart wait: return as soon as new output is available or process exits,
        # instead of unconditionally sleeping the full wait_ms.
        if wait_ms > 0 and session.exit_code is None:
            deadline = time.time() + min(wait_ms, 2000) / 1000.0
            check_interval = 0.05  # check every 50ms
            while time.time() < deadline:
                has_new = (
                    session.stdout_seq > last_stdout_seq
                    or session.stderr_seq > last_stderr_seq
                    or session.exit_code is not None
                    or session.process.returncode is not None
                )
                if has_new:
                    # Small extra wait to batch rapid successive output chunks
                    await asyncio.sleep(0.05)
                    break
                await asyncio.sleep(check_interval)

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
            # Strip ANSI sequences before matching to avoid false negatives in PTY mode
            raw_tail = (stdout_text + "\n" + stderr_text)[-2048:]
            tail_text = self._strip_ansi(raw_tail)

            last_output_ts = session.created_at
            if session.stdout_chunks:
                last_output_ts = max(last_output_ts, session.stdout_chunks[-1].timestamp)
            if session.stderr_chunks:
                last_output_ts = max(last_output_ts, session.stderr_chunks[-1].timestamp)
            silence_ms = int(max(0.0, (time.time() - last_output_ts) * 1000))

            prompt_type: Optional[str] = None
            prompt_options: List[dict] = []
            prompt_default: Optional[str] = None

            if state == "running":
                # 使用带类型标注的模式进行检测（在 ANSI 剥离后的文本上）
                detected_type, detected_prompt = self._detect_prompt_type(tail_text)
                if detected_type:
                    state = "waiting_input"
                    waiting_reason = "prompt_pattern"
                    matched_prompt = detected_prompt
                    prompt_type = detected_type

                    # 根据类型进行额外解析
                    if detected_type == "select":
                        prompt_options = self._parse_select_options(tail_text)
                        # 如果没有解析到选项，降级为 text 类型
                        if not prompt_options:
                            prompt_type = "text"
                    elif detected_type == "confirm":
                        prompt_default = self._parse_confirm_default(tail_text)

                if state == "running" and silence_ms >= self._maybe_waiting_silence_ms:
                    state = "maybe_waiting_input"
                    waiting_reason = "silence_timeout"
                    # 即使是静默超时，也尝试检测 prompt 类型（可能是模式匹配
                    # 未覆盖到的 confirm/select 提示）
                    silence_type, silence_prompt = self._detect_prompt_type(tail_text)
                    if silence_type:
                        prompt_type = silence_type
                        matched_prompt = silence_prompt
                        if silence_type == "select":
                            prompt_options = self._parse_select_options(tail_text)
                            if not prompt_options:
                                prompt_type = "text"
                        elif silence_type == "confirm":
                            prompt_default = self._parse_confirm_default(tail_text)
                    else:
                        prompt_type = "text"  # 无法检测则默认 text

            session.mark_active()
            logger.debug(
                "[INTERACTIVE-POLL] session_id=%s state=%s exit_code=%s "
                "stdout_len=%s stderr_len=%s next_stdout_seq=%s next_stderr_seq=%s "
                "prompt_type=%s prompt_options_len=%s prompt_default=%s "
                "waiting_reason=%s matched_prompt=%s silence_ms=%s last_stdout_seq=%s last_stderr_seq=%s",
                session_id,
                state,
                session.exit_code,
                len(stdout_text or ""),
                len(stderr_text or ""),
                session.stdout_seq,
                session.stderr_seq,
                prompt_type,
                len(prompt_options or []),
                prompt_default,
                waiting_reason,
                matched_prompt,
                silence_ms,
                last_stdout_seq,
                last_stderr_seq,
            )
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
                "prompt_type": prompt_type,
                "prompt_options": prompt_options,
                "prompt_default": prompt_default,
            }

    async def resize(self, session_id: str, rows: int, cols: int) -> dict:
        """Adjust PTY terminal window size."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"interactive session not found: {session_id}")
        if session.exit_code is not None:
            return {
                "session_id": session_id,
                "error": "session already exited",
            }
        if not session.use_pty or session.master_fd is None:
            return {
                "session_id": session_id,
                "error": "resize is only supported in PTY mode",
            }

        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(session.master_fd, termios.TIOCSWINSZ, winsize)
            session.process.send_signal(signal.SIGWINCH)
        except OSError as exc:
            return {
                "session_id": session_id,
                "error": f"resize failed: {exc}",
            }

        session.mark_active()
        return {
            "session_id": session_id,
            "rows": rows,
            "cols": cols,
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
                    try:
                        await asyncio.wait_for(session.process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"[INTERACTIVE] Process did not exit after kill: "
                            f"session_id={session_id}, pid={session.process.pid}"
                        )

            session.exit_code = session.process.returncode
            session.mark_active()
        finally:
            # IMPORTANT: Close PTY master fd FIRST to unblock any os.read()
            # threads. On macOS, os.close() on a FD can block if another
            # thread is in os.read() on the same FD, but closing it will
            # cause os.read() to return with EBADF, breaking the deadlock.
            if session.master_fd is not None:
                try:
                    os.close(session.master_fd)
                except OSError:
                    pass
                session.master_fd = None

            # Cancel read tasks (after closing FD to unblock threads)
            for task_attr in ('read_task', 'stdout_task', 'stderr_task'):
                task = getattr(session, task_attr, None)
                if task and not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                        pass

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
