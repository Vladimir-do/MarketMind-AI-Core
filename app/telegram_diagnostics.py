import asyncio
import re
import socket
import ssl
import time
from urllib.parse import urlparse

import certifi


def mask_proxy_url(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return "не задан"
    parsed = urlparse(value)
    if not parsed.scheme:
        return "***"
    host = parsed.hostname or "unknown-host"
    port = f":{parsed.port}" if parsed.port else ""
    if parsed.username or parsed.password:
        return f"{parsed.scheme}://***@{host}{port}"
    return f"{parsed.scheme}://{host}{port}"


async def probe_dns(host: str) -> tuple[bool, str]:
    started = time.perf_counter()
    try:
        infos = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, 443), timeout=4.0)
    except Exception as exc:
        return False, f"ошибка ({type(exc).__name__}: {exc})"
    latency_ms = int((time.perf_counter() - started) * 1000)
    unique_ips = sorted({item[4][0] for item in infos if item and item[4]})
    if not unique_ips:
        return False, f"пустой ответ ({latency_ms} ms)"
    return True, f"ok ({latency_ms} ms), IP: {', '.join(unique_ips[:3])}"


async def probe_tcp(host: str, port: int) -> tuple[bool, str]:
    started = time.perf_counter()
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host=host, port=port), timeout=5.0)
        if reader.at_eof():
            return False, "соединение закрыто удалённой стороной"
    except Exception as exc:
        return False, f"ошибка ({type(exc).__name__}: {exc})"
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
    latency_ms = int((time.perf_counter() - started) * 1000)
    return True, f"ok ({latency_ms} ms)"


async def probe_https(host: str) -> tuple[bool, str]:
    started = time.perf_counter()
    writer = None
    try:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host=host, port=443, ssl=ssl_ctx, server_hostname=host),
            timeout=7.0,
        )
        request = (
            f"HEAD / HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "User-Agent: parser-agent-netdiag/1.0\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        first_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not first_line:
            return False, "пустой ответ"
        status_line = first_line.decode("latin-1", errors="replace").strip()
        match = re.match(r"HTTP/\d\.\d\s+(\d{3})", status_line)
        if not match:
            return False, f"непонятный ответ ({status_line})"
        status_code = int(match.group(1))
    except Exception as exc:
        return False, f"ошибка ({type(exc).__name__}: {exc})"
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
    latency_ms = int((time.perf_counter() - started) * 1000)
    return True, f"HTTP {status_code} ({latency_ms} ms)"
