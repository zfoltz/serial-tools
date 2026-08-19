"""The TX gate that matters most: send_bytes must not exist without --allow-tx."""

import asyncio

from serialtools.mcp import server


def _tool_names():
    return {t.name for t in asyncio.run(server.mcp.list_tools())}


def test_send_bytes_absent_by_default_then_registered_and_gated():
    names = _tool_names()
    assert "send_bytes" not in names, "TX tool must not exist without --allow-tx"
    for expected in ("list_ports", "detect_settings", "start_tap", "tap_status",
                     "get_frames", "stop_tap", "list_captures", "decode_capture",
                     "analyze_capture"):
        assert expected in names

    server._register_send(server.mcp)
    assert "send_bytes" in _tool_names()

    # Gate 2: wrong confirm string is refused before any port is touched.
    result = asyncio.run(server.mcp.call_tool(
        "send_bytes", {"port": "COM99", "data_hex": "4350", "confirm": "yes"}))
    text = str(result)
    assert "refused" in text and "SEND COM99" in text
