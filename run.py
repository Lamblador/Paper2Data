#!/usr/bin/env python3
"""Запуск Paper2Data: FastAPI + (опционально) раздача frontend/dist."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper2Data — локальный сервер")
    parser.add_argument("--host", default=os.environ.get("PAPER2DATA_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PAPER2DATA_PORT", "8765")),
    )
    parser.add_argument("--no-browser", action="store_true", help="Не открывать браузер")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Автоперезагрузка (только backend, без статики)",
    )
    args = parser.parse_args()

    static_dir = ROOT / "frontend" / "dist"
    if not static_dir.exists():
        print(
            f"[Paper2Data] Сборка фронтенда не найдена ({static_dir}).\n"
            "  Для разработки: cd frontend && npm install && npm run dev\n"
            "  Для продакшен-сборки: cd frontend && npm run build\n"
            "  API будет доступно на /api/*",
            flush=True,
        )
        static_dir = None

    import uvicorn

    from paper2data.api.app import create_app
    from paper2data.core.config import settings

    settings.host = args.host
    settings.port = args.port

    app = create_app(static_dir=static_dir)
    url = f"http://{args.host}:{args.port}"

    if not args.no_browser:

        def _open() -> None:
            time.sleep(1.2)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    print(f"[Paper2Data] Сервер: {url}", flush=True)
    uvicorn.run(
        app if not args.reload else "paper2data.api.app:create_app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        factory=args.reload,
        app_dir=str(BACKEND) if args.reload else None,
    )


if __name__ == "__main__":
    main()
