#!/usr/bin/env python3
"""拉取 Docker 构建所需的第三方二进制。

仓库不收录 vendor/ 下的二进制(见 .gitignore),新克隆的仓库直接
`docker compose up` 会在 Dockerfile 的 COPY 阶段失败。本脚本把它们准备好,
可重复执行(已存在且大小一致就跳过)。

    python tools/prepare.py            # 拉两个二进制
    python tools/prepare.py --force    # 忽略已有文件重新下载

前端不需要本脚本:Dockerfile 里有 node 阶段,镜像内自行构建。
只有「零 Docker」开发流才需要自己 cd web && npm ci && npm run build。

版本是钉死的:换版本时改下面两个常量,并同步更新 Dockerfile 的 COPY 行
(文件名里的版本号必须一致)。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"

GO2RTC_VERSION = "1.9.14"
ORCA_VERSION = "2.4.2"

# sha256 为人工实测值(与上游 release 资产逐字节一致)。
# 上游 go2rtc 另附 SHA256SUMS 可交叉核对;OrcaSlicer 未发布校验文件。
GO2RTC_SHA256 = {
    "amd64": "32d616af226bd731678ffde328b94cfb94e30339bfefc469cfb76323144615a6",
    "arm64": None,  # 未实测,下载后不校验
}
ORCA_SHA256 = {
    "amd64": "d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd",
    "arm64": None,
}


def arch() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "amd64"


def human(n: int) -> str:
    return f"{n / 1024 ** 2:.1f} MB" if n > 1024 * 1024 else f"{n / 1024:.0f} KB"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path, expect_size: int, expect_sha: str | None,
          force: bool) -> None:
    if dest.exists() and not force:
        actual = dest.stat().st_size
        if actual == expect_size:
            print(f"  已存在 {dest.relative_to(ROOT)}({human(actual)}),跳过")
            return
        print(f"  {dest.relative_to(ROOT)} 大小不符"
              f"(本地 {human(actual)} != 期望 {human(expect_size)}),重新下载")

    print(f"  下载 {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as fh:
        done = 0
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            done += len(chunk)
            print(f"\r    {human(done)}", end="", flush=True)
    print()

    size = tmp.stat().st_size
    if size != expect_size:
        tmp.unlink(missing_ok=True)
        sys.exit(f"下载大小不符:得到 {human(size)},期望 {human(expect_size)}")

    if expect_sha:
        got = sha256(tmp)
        if got != expect_sha:
            tmp.unlink(missing_ok=True)
            sys.exit(f"sha256 校验失败:\n  期望 {expect_sha}\n  实际 {got}")
        print(f"    sha256 校验通过")

    tmp.replace(dest)


def go2rtc(a: str, force: bool) -> None:
    print("[1/2] go2rtc(摄像头 sidecar)")
    url = (f"https://github.com/AlexxIT/go2rtc/releases/download/"
           f"v{GO2RTC_VERSION}/go2rtc_linux_{a}")
    dest = VENDOR / "go2rtc" / "go2rtc"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 未实测的架构不校验大小,传 0 表示跳过大小检查
    fetch(url, dest, 5726972 if a == "amd64" else 0,
          GO2RTC_SHA256.get(a), force)
    if os.name != "nt":
        dest.chmod(0o755)


def orca(a: str, force: bool) -> None:
    print("[2/2] OrcaSlicer AppImage(切片引擎)")
    # 上游资产命名:amd64 段不带架构后缀,aarch64 带 _aarch64
    stem = "OrcaSlicer_Linux_AppImage_Ubuntu2404"
    name = (f"{stem}_V{ORCA_VERSION}.AppImage" if a == "amd64"
            else f"{stem}_aarch64_V{ORCA_VERSION}.AppImage")
    url = f"https://github.com/SoftFever/OrcaSlicer/releases/download/v{ORCA_VERSION}/{name}"
    dest = VENDOR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if a != "amd64":
        print("  注意:server/Dockerfile 的 COPY 行写死了 amd64 文件名,"
              "arm64 需自行改 Dockerfile 后再构建。")
    fetch(url, dest, 137759224 if a == "amd64" else 0,
          ORCA_SHA256.get(a), force)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="忽略已有文件重新下载")
    args = ap.parse_args()

    a = arch()
    print(f"平台: {platform.system()} {platform.machine()} (架构判定 {a})\n")
    go2rtc(a, args.force)
    orca(a, args.force)
    print("\n准备完成。下一步:")
    print("  docker compose up -d --build   # 自托管单机版,访问 http://<主机IP>:8002")
    print("  docker compose logs -f server")


if __name__ == "__main__":
    main()