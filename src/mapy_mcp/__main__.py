"""Spuštění serveru.

Server startuje i bez API klíče — jinak by klient hlásil jen „MCP server failed“
a uživatel by neměl co ladit. Chybějící klíč se ohlásí až při volání nástroje,
s instrukcí, kde ho vzít.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .server import create_server


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="mapy-cz-mcp-server-unofficial",
        description="Neoficiální MCP server pro REST API Mapy.com.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio pro lokální klienty (výchozí), http pro streamable HTTP.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Adresa pro --transport http.")
    parser.add_argument("--port", type=int, default=8000, help="Port pro --transport http.")
    args = parser.parse_args()

    # httpx loguje každý požadavek na INFO. Ve stdio režimu to jde klientovi do
    # logu jako šum, včetně celých URL — tlumíme na WARNING.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    server = create_server()
    if args.transport == "http":
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
