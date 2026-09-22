from __future__ import annotations

import argparse
import importlib.util

import uvicorn


def _ensure_websocket_runtime() -> None:
    if importlib.util.find_spec("websockets") is not None:
        return
    if importlib.util.find_spec("wsproto") is not None:
        return
    raise SystemExit(
        "Web 服务缺少 WebSocket 运行依赖，任务状态无法实时推送。"
        "请重新执行 `python -m pip install -e .` 后再启动。"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ehrm-web",
        description="启动信息化人力工作台 Web 服务（单服务器、单协调器实例）。",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="仅用于本地开发")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _ensure_websocket_runtime()
    uvicorn.run(
        "ehrm.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
