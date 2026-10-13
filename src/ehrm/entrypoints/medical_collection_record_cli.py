"""Manual, evidence-rich recording of medical and social-security flows.

This recorder never clicks Save/Submit. The operator performs the complete
flow in the visible browser while actions, portal requests and before/after
page state are captured for later implementation and review.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, UTC
import json
import os
from pathlib import Path
from queue import Queue
import re
import sys
from threading import Thread
from time import sleep
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, Request, sync_playwright

from ehrm.core.runtime import application_runtime_root, resolve_runtime_path
from ehrm.core.settings import DEFAULT_SETTINGS_PATH
from ehrm.modules.medical_termination.page import MEDICAL_LOGIN_URL, is_medical_portal_url


_MEDICAL_HOST = "wb.njybjyybz.org.cn"
_SOCIAL_HOST = "rs.jshrss.jiangsu.gov.cn"
SOCIAL_LOGIN_URL = f"https://{_SOCIAL_HOST}/web/login"
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_MAX_BODY_CHARS = 2_000_000


def _is_business_page(url: str, system: str) -> bool:
    if system == "medical":
        return is_medical_portal_url(url)
    parts = urlsplit(url)
    return parts.hostname == _SOCIAL_HOST and parts.path.startswith("/web/") and parts.path != "/web/login"


def _is_business_api_host(url: str, system: str) -> bool:
    host = urlsplit(url).hostname or ""
    if system == "medical":
        return host == _MEDICAL_HOST
    return host == _SOCIAL_HOST or host.endswith(".jshrss.jiangsu.gov.cn")

_ACTION_SCRIPT = r"""
(() => {
  const capture = window.__ehrmMedicalCollectionCaptureV1;
  if (typeof capture !== 'function') return;
  const pathOf = element => {
    const segments = [];
    for (let node = element, depth = 0; node && depth < 6; node = node.parentElement, depth++) {
      if (node.id) { segments.unshift('#' + CSS.escape(node.id)); break; }
      let segment = node.tagName.toLowerCase();
      const classes = [...node.classList].filter(x => !/^is-|^el-icon-/.test(x)).slice(0, 2);
      if (classes.length) segment += classes.map(x => '.' + CSS.escape(x)).join('');
      if (node.parentElement) {
        const siblings = [...node.parentElement.children].filter(x => x.tagName === node.tagName);
        if (siblings.length > 1) segment += ':nth-of-type(' + ([...node.parentElement.children].filter(x => x.tagName === node.tagName).indexOf(node) + 1) + ')';
      }
      segments.unshift(segment);
    }
    return segments.join(' > ');
  };
  for (const name of ['click', 'change', 'submit']) {
    document.addEventListener(name, event => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target) return;
      const element = target.closest('button,a,input,select,textarea,[role="button"],.el-select-dropdown__item') || target;
      const label = element.getAttribute('aria-label') || element.getAttribute('placeholder') ||
        element.closest('.el-form-item')?.querySelector('label')?.textContent ||
        (element instanceof HTMLInputElement ? '' : element.textContent) || '';
      capture({type: name, selector: pathOf(element), label: label.trim().slice(0, 120),
        tag: element.tagName, inputType: element.getAttribute('type') || ''}).catch(() => {});
    }, true);
  }
})();
"""

_FIELDS_SCRIPT = r"""() => [...document.querySelectorAll('input,select,textarea,button')]
  .filter(element => element.getClientRects().length > 0)
  .map(element => {
    const label = element.closest('.el-form-item')?.querySelector('label')?.textContent ||
      (element.id ? document.querySelector('label[for="' + CSS.escape(element.id) + '"]')?.textContent : '') || '';
    const type = element.getAttribute('type') || '';
    return {tag: element.tagName, type, id: element.id, name: element.getAttribute('name'),
      placeholder: element.getAttribute('placeholder'), label: label.trim(),
      value: type === 'password' ? '[REDACTED]' : ('value' in element ? element.value : ''),
      text: element.tagName === 'BUTTON' ? element.textContent.trim().slice(0, 120) : '',
      disabled: element.disabled || false, readonly: element.readOnly || false};
  })"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_private(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


class Capture:
    def __init__(self, output_dir: Path, *, system: str = "medical") -> None:
        if system not in {"medical", "social"}:
            raise ValueError(f"不支持的业务系统：{system}")
        self.output_dir = output_dir
        self.system = system
        self.phase = "login_and_fill"
        self.requests: list[dict[str, object]] = []
        self.actions = 0
        self.action_file = (output_dir / "actions.jsonl").open("x", encoding="utf-8")
        network_path = output_dir / f"{system}-network.jsonl"
        self.network_file = network_path.open("x", encoding="utf-8")
        for path in (output_dir / "actions.jsonl", network_path):
            path.chmod(0o600)

    @staticmethod
    def _write_line(file, row: dict[str, object]) -> None:
        file.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        file.flush()

    def action(self, source, payload: dict[str, object]) -> None:
        self.actions += 1
        self._write_line(self.action_file, {
            "at": _now(), "phase": self.phase, "frame_url": source["frame"].url, **payload,
        })

    def request_finished(self, request: Request) -> None:
        if not _is_business_api_host(request.url, self.system) or request.resource_type not in {"xhr", "fetch"}:
            return
        response = request.response()
        content_type = response.headers.get("content-type", "") if response else ""
        body = ""
        if response and any(value in content_type for value in ("json", "text", "xml")):
            try:
                body = response.text()[:_MAX_BODY_CHARS]
            except PlaywrightError as exc:
                body = f"[读取响应失败：{exc}]"
        record: dict[str, object] = {
            "at": _now(), "phase": self.phase, "method": request.method,
            "url": request.url, "status": response.status if response else None,
            "request_body": (request.post_data or "")[:_MAX_BODY_CHARS],
            "response_content_type": content_type, "response_body": body,
        }
        self.requests.append(record)
        self._write_line(self.network_file, record)

    def request_failed(self, request: Request) -> None:
        if not _is_business_api_host(request.url, self.system) or request.resource_type not in {"xhr", "fetch"}:
            return
        record = {
            "at": _now(), "phase": self.phase, "method": request.method,
            "url": request.url, "status": None, "request_body": (request.post_data or "")[:_MAX_BODY_CHARS],
            "failure": request.failure,
        }
        self.requests.append(record)
        self._write_line(self.network_file, record)

    def close(self) -> None:
        self.action_file.close()
        self.network_file.close()

    def summary(self) -> dict[str, object]:
        calls = [row for row in self.requests if row["phase"] == "submit_and_post"]
        non_get = [row for row in calls if row["method"] in _MUTATING_METHODS]
        medical_submissions = [
            row for row in self.requests
            if self.system == "medical" and row["method"] == "POST"
            and urlsplit(str(row["url"])).path.endswith((
                "/api/ryda/saveRydainfo", "/api/dwctbbl/rycbdj/saveInfo",
            ))
        ]
        endpoints = Counter(
            (str(row["method"]), re.sub(r"\d{8,}", "{id}", urlsplit(str(row["url"])).path), row["status"])
            for row in calls
        )
        return {
            "captured_at": _now(), "actions": self.actions,
            f"{self.system}_api_total": len(self.requests),
            f"{self.system}_api_after_pre_submit": len(calls),
            "portal_api_total": len(self.requests),
            "non_get_api_after_pre_submit": len(non_get),
            "medical_business_submissions_all_phases": [
                {"phase": row["phase"], "path": urlsplit(str(row["url"])).path, "status": row["status"]}
                for row in medical_submissions
            ],
            "endpoints_after_pre_submit": [
                {"method": method, "path": path, "status": status, "count": count}
                for (method, path, status), count in sorted(endpoints.items(), key=lambda item: str(item[0]))
            ],
            "warning": (
                "未捕获医保建档或参保提交接口；请检查实际操作和录制文件"
                if self.system == "medical" and not medical_submissions
                else "未捕获提交阶段的社保 POST/PUT/PATCH/DELETE 请求；录制不能用于判断提交接口"
                if self.system == "social" and not non_get else ""
            ),
        }


def _read_stdin(lines: Queue[str]) -> None:
    for line in sys.stdin:
        lines.put(line)
    lines.put("__EOF__")


def _wait_for_enter(context: BrowserContext, lines: Queue[str], prompt: str) -> None:
    print(prompt, flush=True)
    while lines.empty():
        pages = [page for page in context.pages if not page.is_closed()]
        if pages:
            try:
                pages[-1].wait_for_timeout(200)
            except PlaywrightError:
                pass
        else:
            sleep(0.2)
    if lines.get() == "__EOF__":
        raise EOFError("终端输入已关闭，录制提前结束")


def _snapshot(context: BrowserContext, output_dir: Path, name: str, *, system: str = "medical") -> None:
    pages = [page for page in context.pages if not page.is_closed() and _is_business_page(page.url, system)]
    if not pages:
        portal_name = "南京医保单位大厅" if system == "medical" else "智慧人社业务页面"
        raise RuntimeError(f"{name} 时未找到{portal_name}；请勿将本次录制视为完整")
    page: Page = pages[-1]
    page.screenshot(path=str(output_dir / f"{name}.png"), full_page=True)
    (output_dir / f"{name}.png").chmod(0o600)
    frames = []
    for index, frame in enumerate(page.frames):
        row: dict[str, object] = {"index": index, "url": frame.url, "name": frame.name}
        try:
            row["fields"] = frame.evaluate(_FIELDS_SCRIPT)
            _write_private(output_dir / f"{name}-frame-{index}.html", frame.content())
        except PlaywrightError as exc:
            row["error"] = str(exc)
        frames.append(row)
    _write_private(output_dir / f"{name}-fields.json", json.dumps({
        "at": _now(), "page_url": page.url, "frames": frames,
    }, ensure_ascii=False, indent=2))


def _record(profile: Path, output_dir: Path, url: str, *, flow: str = "collection", system: str = "medical") -> int:
    flow_names = {
        ("medical", "collection"): "人员基础信息采集",
        ("medical", "enrollment"): "人员参保登记",
        ("social", "information"): "人员信息维护",
        ("social", "enrollment"): "用工参保登记",
    }
    flow_name = flow_names.get((system, flow))
    if flow_name is None:
        print(f"不支持的录制流程：{system}/{flow}", file=sys.stderr)
        return 2
    if output_dir.exists():
        print(f"输出目录已存在，拒绝覆盖旧录制：{output_dir}", file=sys.stderr)
        return 2
    entry_host = "www.jszwfw.gov.cn" if system == "medical" else _SOCIAL_HOST
    if urlsplit(url).hostname != entry_host:
        print(f"录制入口必须是 {entry_host}", file=sys.stderr)
        return 2
    output_dir.mkdir(parents=True, mode=0o700)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    old_umask = os.umask(0o077)
    capture = Capture(output_dir, system=system)
    lines: Queue[str] = Queue()
    Thread(target=_read_stdin, args=(lines,), daemon=True).start()
    status = 0
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile), headless=False, accept_downloads=True,
                record_har_path=str(output_dir / "all-network.har"),
                record_har_content="embed", record_har_mode="full",
            )
            context.expose_binding("__ehrmMedicalCollectionCaptureV1", capture.action)
            context.add_init_script(_ACTION_SCRIPT)
            context.on("requestfinished", capture.request_finished)
            context.on("requestfailed", capture.request_failed)

            def attach_page(page: Page) -> None:
                page.on("pageerror", lambda error: capture._write_line(capture.action_file, {
                    "at": _now(), "phase": capture.phase, "type": "pageerror", "message": str(error),
                }))
                page.on("dialog", lambda dialog: _handle_dialog(dialog, lines))

            context.on("page", attach_page)
            for page in context.pages:
                attach_page(page)
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            portal_name = "医保平台" if system == "medical" else "八化建的智慧人社"
            print(f"录制浏览器已打开。请手动登录{portal_name}，进入“{flow_name}”，填写测试人员资料。")
            print("此脚本不会代替你点击“确认/保存/提交”。HAR、页面快照及接口正文含个人信息和令牌，请勿直接分享。")
            try:
                _wait_for_enter(context, lines, "填写完毕、尚未点击最终确认/提交时，回终端按 Enter：")
                _snapshot(context, output_dir, "before-submit", system=system)
                capture.phase = "submit_and_post"
                _wait_for_enter(context, lines, "现在在浏览器中完成所有确认、保存或提交，并查看成功/失败及后续查询状态；全部稳定后按 Enter：")
                _snapshot(context, output_dir, "after-submit", system=system)
            finally:
                try:
                    context.tracing.stop(path=str(output_dir / "trace.zip"))
                    (output_dir / "trace.zip").chmod(0o600)
                finally:
                    context.close()
    except (PlaywrightError, RuntimeError, EOFError, KeyboardInterrupt) as exc:
        print(f"录制未完整结束：{exc}", file=sys.stderr)
        status = 1
    finally:
        capture.close()
        os.umask(old_umask)
    summary = capture.summary()
    _write_private(output_dir / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"录制文件：{output_dir}")
    portal_name = "医保" if system == "medical" else "社保"
    print(f"{portal_name}接口 {summary['portal_api_total']} 条；提交阶段 POST/PUT/PATCH/DELETE 请求 {summary['non_get_api_after_pre_submit']} 条（需分析内容辨认提交接口）。")
    if summary["warning"]:
        print(summary["warning"], file=sys.stderr)
        return 3 if status == 0 else status
    return status


def _handle_dialog(dialog, lines: Queue[str]) -> None:
    print(f"检测到浏览器原生弹窗：{dialog.type}：{dialog.message}", flush=True)
    print("仅当你确定要继续真实提交时，在终端输入 y 再按 Enter；其他输入将取消弹窗：", flush=True)
    answer = lines.get().strip().lower()
    if answer in {"y", "yes"}:
        dialog.accept()
    else:
        dialog.dismiss()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="完整录制医保人员基础信息采集或参保登记的手工操作、业务接口及提交前后状态")
    parser.add_argument("--flow", choices=("collection", "enrollment"), default="collection", help="采集或参保登记；默认采集")
    parser.add_argument("--profile", type=Path, help="独立的录制浏览器目录；默认按流程分别保存")
    parser.add_argument("--output-dir", type=Path, help="录制证据目录；默认按流程与时间戳新建")
    parser.add_argument("--url", default=MEDICAL_LOGIN_URL)
    args = parser.parse_args(argv)
    root = application_runtime_root(DEFAULT_SETTINGS_PATH)
    profile = args.profile or Path(f"data/medical-{args.flow}-record-profile")
    output_dir = args.output_dir or Path(
        f"artifacts/medical-{args.flow}-full-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    return _record(resolve_runtime_path(profile, root), resolve_runtime_path(output_dir, root), args.url, flow=args.flow)


if __name__ == "__main__":
    raise SystemExit(main())
