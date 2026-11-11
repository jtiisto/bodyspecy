"""Reach the tools and instructions a FastMCP server exposes, through its public API."""

import asyncio
from concurrent.futures import ThreadPoolExecutor


def list_tools(mcp_server):
    """Return the tool objects `mcp_server` lists, in listing order.

    `list_tools()` is a coroutine. It runs on a worker thread with a loop of
    its own, so the helper works from a plain synchronous test whether or not
    the calling thread already has a running event loop (the suite's
    pytest-asyncio tests share this process).
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, mcp_server.list_tools()).result()


def server_instructions(mcp_server):
    """Return the `instructions` `mcp_server` sends a client, or None.

    Read the way a client reads them: an in-memory `fastmcp.Client` performs
    the MCP initialize handshake (`mode="legacy"` pins the classic
    `initialize` request rather than FastMCP 4's newer negotiation) and the
    text is taken from its `InitializeResult`. Same worker-thread pattern as
    `list_tools`.
    """
    from fastmcp import Client

    async def handshake():
        async with Client(mcp_server, mode="legacy") as client:
            return client.initialize_result.instructions

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, handshake()).result()
