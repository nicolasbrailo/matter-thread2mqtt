"""Long-lived matter-server connection, on its own asyncio loop in a background thread.

matter-server keeps a live cache of every node's attributes and streams updates while we
stay connected, so we connect once and keep the connection (reconnecting forever) instead
of connecting per request.
"""
import asyncio
import threading

import aiohttp
from matter_server.client import MatterClient

MATTER_URL = "ws://127.0.0.1:5580/ws"
RECONNECT_DELAY = 5


def log(msg):
    print(f"[matter] {msg}", flush=True)


class Matter:
    def __init__(self, on_connect, on_disconnect):
        """on_connect(client) runs on the matter loop after every (re)connect, once the node cache
        is populated; on_disconnect() when that connection drops (nothing is known any more)."""
        self.client = None
        self.loop = asyncio.new_event_loop()
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        threading.Thread(target=self.loop.run_until_complete, args=(self._run(),), daemon=True).start()

    async def _run(self):
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    client = MatterClient(MATTER_URL, session)
                    await client.connect()
                    init = asyncio.Event()
                    listen = asyncio.create_task(client.start_listening(init))
                    ready = asyncio.create_task(init.wait())
                    # start_listening may die before it ever gets the node dump
                    await asyncio.wait({listen, ready}, return_when=asyncio.FIRST_COMPLETED)
                    ready.cancel()
                    if init.is_set():
                        log(f"connected, {len(client.get_nodes())} node(s)")
                        self.client = client
                        try:
                            self._on_connect(client)
                        except Exception as e:
                            log(f"on_connect failed: {e!r}")
                    await listen  # returns (or raises) when the connection drops
                    log("disconnected")
            except Exception as e:
                log(f"connection to {MATTER_URL} failed: {e!r}")
            self.client = None
            try:
                self._on_disconnect()
            except Exception as e:
                log(f"on_disconnect failed: {e!r}")
            await asyncio.sleep(RECONNECT_DELAY)

    def submit(self, coro):
        """Run a coroutine on the matter loop from another thread; don't wait for it."""
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        fut.add_done_callback(_log_failure)


def _log_failure(fut):
    if not fut.cancelled() and fut.exception() is not None:
        log(f"task failed: {fut.exception()!r}")
