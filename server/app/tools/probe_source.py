"""模型源连通性探测:验证搜索/详情/下载解析(不落盘)。

用法:
  python -m app.tools.probe_source --keyword 龙 --region cn
  python -m app.tools.probe_source --design 931489 --token <你的token>
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.sources.makerworld import MakerWorldAdapter


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", default="")
    ap.add_argument("--design", default="")
    ap.add_argument("--region", default="cn", choices=["cn", "com"])
    ap.add_argument("--token", default="")
    args = ap.parse_args()

    mw = MakerWorldAdapter(token=args.token, region=args.region)
    try:
        if args.keyword:
            total, items = await mw.search(args.keyword, page=1, page_size=5)
            print(f"搜索[{args.keyword}] 共 {total} 条,前 5:")
            for it in items:
                print(f"  {it.id:>10}  {it.title[:30]:<32} ♥{it.likes} ↓{it.downloads} {it.author}")
            if items:
                args.design = args.design or items[0].id
        if args.design:
            d = await mw.design(args.design)
            print(f"\n设计 {d.id}: {d.title} (作者 {d.author})")
            print(f"  页面: {d.source_url}")
            for i in d.instances[:5]:
                print(f"  实例 {i.instance_id} profile={i.profile_id} {i.name[:40]}")
            if args.token and d.instances:
                url, fname = await mw.resolve_download(d, d.instances[0])
                print(f"  [token 有效] 直链: {url[:90]}... 文件: {fname}")
            elif not args.token:
                print("  (未提供 token,跳过下载直链解析)")
    finally:
        await mw.aclose()


if __name__ == "__main__":
    asyncio.run(main())
