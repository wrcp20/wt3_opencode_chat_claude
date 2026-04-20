from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from dataclasses import dataclass, field

from backend.app.config import AppConfig


DONE_EVENT = {"type": "done"}


@dataclass
class PendingRequest:
    text: str
    events: asyncio.Queue[dict[str, str]] = field(default_factory=asyncio.Queue)
    text_sent: int = 0
    is_probe: bool = False


class ClaudeCLISession:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.model = config.validate_model(config.claude_model)
        self.proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._buffer = ""
        self._ready = False
        self._warming = False
        self._queue: deque[PendingRequest] = deque()
        self._active: PendingRequest | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            await self._start_locked()

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def reset(self, model: str | None = None) -> None:
        async with self._lock:
            if model:
                self.model = self.config.validate_model(model)
            await self._fail_all_locked("Nueva conversacion")
            await self._stop_locked()
            await self._start_locked()

    async def send(self, text: str) -> asyncio.Queue[dict[str, str]]:
        request = PendingRequest(text=text)
        async with self._lock:
            if self.proc is None:
                await self._start_locked()
            self._queue.append(request)
            await self._dispatch_next_locked()
        return request.events

    def remove_queued(self, events: asyncio.Queue[dict[str, str]]) -> None:
        self._queue = deque(request for request in self._queue if request.events is not events)

    def status(self) -> dict[str, object]:
        return {
            "ok": True,
            "model": self.model,
            "ready": self._ready,
            "warming": self._warming,
            "queue": len(self._queue),
        }

    async def _start_locked(self) -> None:
        if self.proc and self.proc.returncode is None:
            return

        command = [
            "claude",
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--model",
            self.model,
        ]
        if self.config.claude_dangerously_skip_permissions:
            command.append("--dangerously-skip-permissions")

        self.proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._buffer = ""
        self._ready = False
        self._warming = True
        self._reader_task = asyncio.create_task(self._reader_loop())

        probe = PendingRequest(text=self.config.claude_warmup_prompt, is_probe=True)
        self._active = probe
        await self._write_message_locked(probe.text)

    async def _stop_locked(self) -> None:
        proc = self.proc
        self.proc = None
        self._ready = False
        self._warming = False

        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None

    async def _reader_loop(self) -> None:
        assert self.proc and self.proc.stdout

        try:
            while True:
                chunk = await self.proc.stdout.read(4096)
                if not chunk:
                    break
                self._buffer += chunk.decode("utf-8", errors="replace")
                lines = self._buffer.split("\n")
                self._buffer = lines.pop()
                for line in lines:
                    if line.strip():
                        await self._handle_line(line)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_all(f"Claude CLI reader failed: {exc}")
        finally:
            if self.proc and self.proc.returncode is None:
                await self.proc.wait()
            if self.proc is not None:
                await self._fail_all("Claude CLI session ended")

    async def _handle_line(self, line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        async with self._lock:
            if self._active is None:
                return

            if self._active.is_probe:
                if event.get("type") == "result":
                    self._warming = False
                    self._ready = True
                    self._active = None
                    await self._dispatch_next_locked()
                return

            if event.get("type") == "stream_event":
                delta = event.get("event", {}).get("delta", {})
                if delta.get("type") == "text_delta" and delta.get("text"):
                    self._active.text_sent += 1
                    await self._active.events.put({"type": "text", "text": delta["text"]})
                return

            if event.get("type") == "result":
                result_text = event.get("result") or ""
                if not self._active.text_sent and result_text:
                    await self._active.events.put({"type": "text", "text": result_text})
                if event.get("is_error"):
                    await self._active.events.put({"type": "error", "error": result_text or "Claude CLI error"})
                await self._active.events.put(DONE_EVENT)
                self._active = None
                await self._dispatch_next_locked()

    async def _dispatch_next_locked(self) -> None:
        if not self._ready or self._active is not None or not self._queue:
            return
        self._active = self._queue.popleft()
        await self._write_message_locked(self._active.text)

    async def _write_message_locked(self, text: str) -> None:
        assert self.proc and self.proc.stdin
        payload = json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                },
            }
        ) + "\n"
        self.proc.stdin.write(payload.encode("utf-8"))
        await self.proc.stdin.drain()

    async def _fail_all(self, message: str) -> None:
        async with self._lock:
            await self._fail_all_locked(message)

    async def _fail_all_locked(self, message: str) -> None:
        targets: list[PendingRequest] = []
        if self._active and not self._active.is_probe:
            targets.append(self._active)
        targets.extend(list(self._queue))
        self._queue.clear()
        self._active = None
        self._ready = False
        self._warming = False
        for request in targets:
            await request.events.put({"type": "error", "error": message})
            await request.events.put(DONE_EVENT)
