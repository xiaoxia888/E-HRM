"""Capture a manually completed social-security information or enrollment flow."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from ehrm.core.runtime import application_runtime_root, resolve_runtime_path
from ehrm.core.settings import DEFAULT_SETTINGS_PATH
from ehrm.entrypoints.medical_collection_record_cli import SOCIAL_LOGIN_URL, _record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="完整录制八化建社保人员信息维护或用工参保登记的手工操作、业务接口及提交前后状态"
    )
    parser.add_argument("--flow", choices=("information", "enrollment"), required=True,
                        help="人员信息维护或用工参保登记")
    parser.add_argument("--profile", type=Path, help="独立的录制浏览器目录；默认按流程分别保存")
    parser.add_argument("--output-dir", type=Path, help="录制证据目录；默认按流程与时间戳新建")
    parser.add_argument("--url", default=SOCIAL_LOGIN_URL)
    args = parser.parse_args(argv)
    root = application_runtime_root(DEFAULT_SETTINGS_PATH)
    profile = args.profile or Path(f"data/bhj-social-{args.flow}-record-profile")
    output_dir = args.output_dir or Path(
        f"artifacts/bhj-social-{args.flow}-full-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    return _record(
        resolve_runtime_path(profile, root),
        resolve_runtime_path(output_dir, root),
        args.url,
        flow=args.flow,
        system="social",
    )


if __name__ == "__main__":
    raise SystemExit(main())
