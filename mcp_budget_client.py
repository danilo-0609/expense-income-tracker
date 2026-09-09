"""Sync-friendly wrapper around the MCP client connection to mcp_sheets_server.py.

ToolCallingExpenseAgent.handle_message is synchronous (mirrors the existing
Anthropic client usage), but the MCP Python SDK's ClientSession is async-only.
This wrapper runs the MCP client session on a dedicated background thread
with its own event loop - spawned once at bot startup and held for the
process's entire lifetime, per the spec - so a query can call
get_budget_status() as a plain blocking call without nesting event loops
inside python-telegram-bot's own asyncio loop.
"""

import asyncio
import json
import logging
import sys
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)

DEFAULT_SERVER_SCRIPT = "mcp_sheets_server.py"
STARTUP_TIMEOUT_SECONDS = 30


class McpBudgetClient:
    """Owns the mcp_sheets_server.py subprocess and its MCP client session."""

    def __init__(self, python_executable: str = None, server_script: str = DEFAULT_SERVER_SCRIPT):
        self._python_executable = python_executable or sys.executable
        self._server_script = server_script
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._stop_event: asyncio.Event | None = None

    def start(self) -> None:
        """Spawn the MCP server subprocess and establish the client session.

        Blocks until the connection is ready (or raises on failure/timeout).
        """
        ready = threading.Event()
        error: list[BaseException] = []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, args=(ready, error), daemon=True)
        self._thread.start()

        if not ready.wait(timeout=STARTUP_TIMEOUT_SECONDS):
            raise RuntimeError("Timed out starting the MCP sheets server subprocess")
        if error:
            raise error[0]
        logger.info("MCP sheets server subprocess started")

    def _run_loop(self, ready: threading.Event, error: list[BaseException]) -> None:
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        self._loop.run_until_complete(self._serve_until_stopped(ready, error))

    async def _serve_until_stopped(self, ready: threading.Event, error: list[BaseException]) -> None:
        # The stdio_client/ClientSession context managers must be entered and
        # exited from the same task (anyio cancel-scope requirement), so the
        # connection, the wait-for-shutdown, and the teardown all happen in
        # this one coroutine/task rather than being split across separate
        # run_until_complete calls.
        server_params = StdioServerParameters(
            command=self._python_executable, args=[self._server_script]
        )
        try:
            async with AsyncExitStack() as exit_stack:
                read_stream, write_stream = await exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                self._session = await exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await self._session.initialize()
                ready.set()
                await self._stop_event.wait()
        except BaseException as exc:  # noqa: BLE001 - surface to the starting thread
            error.append(exc)
            ready.set()

    def get_budget_status(self) -> dict:
        """Call the get_budget_status MCP tool and return the parsed JSON payload.

        Blocking - safe to call from synchronous code running on another thread.
        """
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool("get_budget_status", {}), self._loop
        )
        result = future.result()
        return json.loads(result.content[0].text)

    def get_historical_entries(self, start_date: str, end_date: str, types: list[str]) -> dict:
        """Call the get_historical_entries MCP tool and return the parsed JSON payload.

        Blocking - safe to call from synchronous code running on another thread.
        """
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(
                "get_historical_entries",
                {"start_date": start_date, "end_date": end_date, "types": types},
            ),
            self._loop,
        )
        result = future.result()
        return json.loads(result.content[0].text)

    def stop(self) -> None:
        """Tear down the MCP client session and terminate the subprocess."""
        if self._loop is None or self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._stop_event.set)
        self._thread.join(timeout=STARTUP_TIMEOUT_SECONDS)
        logger.info("MCP sheets server subprocess stopped")
