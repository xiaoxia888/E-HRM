"""Submit sync to an already running E-HRM server; starts no service."""
from __future__ import annotations

import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ERP → NocoBase 同步测试（使用已启动的 E-HRM 服务）")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="E-HRM 地址，不是 NocoBase 地址")
    parser.add_argument("--start-date", default="", help="开始申请日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="结束申请日期 YYYY-MM-DD，包含该日")
    parser.add_argument("--dry-run", action="store_true", help="只查询和预览计划，不写入 NocoBase")
    parser.add_argument("--timeout", type=int, default=600, help="等待任务结束的最长秒数；超时不取消任务")
    args = parser.parse_args(argv)
    if bool(args.start_date) != bool(args.end_date):
        parser.error("开始日期和结束日期必须同时填写")
    if args.timeout < 1:
        parser.error("等待超时必须大于 0")

    def call(path, values=None):
        request = Request(args.server.rstrip("/") + path,
                          data=json.dumps(values).encode() if values is not None else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    try:
        task = call("/api/v1/nocobase/sync", {
            "start_date": args.start_date, "end_date": args.end_date, "dry_run": args.dry_run,
        })
        print(f"任务编号：{task['task_id']}；{task['title']}")
        deadline = time.monotonic() + args.timeout
        previous = ""
        while True:
            task = call(f"/api/v1/tasks/{task['task_id']}")
            if task["message"] != previous:
                print(task["message"])
                previous = task["message"]
            if task["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                print(json.dumps(task.get("result") or {"error": task.get("error")}, ensure_ascii=False, indent=2))
                return 0 if task["status"] == "succeeded" and not (task.get("result") or {}).get("summary", {}).get("failed", 0) else 1
            if time.monotonic() >= deadline:
                print("等待超时，任务可能仍在执行，请到任务中心查看；不会重复创建或自动取消。")
                return 1
            time.sleep(1)
    except HTTPError as exc:
        try:
            print(json.load(exc).get("message", f"HTTP {exc.code}"))
        except (ValueError, AttributeError):
            print(f"E-HRM 接口返回 HTTP {exc.code}")
        return 1
    except (URLError, OSError, ValueError) as exc:
        print(f"无法访问 E-HRM 服务或响应无效：{type(exc).__name__}。请自行启动服务后重试。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
