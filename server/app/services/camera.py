"""摄像头帧服务:go2rtc sidecar 代理。

创想 K 系列(K2/K2 Pro)本地摄像头走私有 WebRTC——信令为
POST base64(SDP offer) 到 http://<打印机IP>:8000/call/webrtc_local,
SDP answer 需跳过首个 codec 并剔除 x-google 行(go2rtc v1.9.9+ 内置
creality 协议,此层不用自己实现)。

部署:go2rtc 以 host 网络容器运行(compose camera 服务),ICE 候选
必须是宿主机 LAN IP,bridge 容器地址打印机不可达(实测结论)。
流按需经 go2rtc API 注册:webrtc:http://<host>:8000/call/webrtc_local#format=creality
"""
import httpx

from app.core.config import settings

# 每次请求都重新 PUT 流定义(幂等、无状态,容忍 camera 容器重启)
# 注意:# 必须保持原样,由 httpx 统一编码成 %23——手工预编码会被二次编码
_SRC = "webrtc:http://{host}:8000/call/webrtc_local#format=creality"


async def go2rtc_frame(printer_id: int, host: str) -> bytes | None:
    """从 go2rtc 取指定打印机的一帧 JPEG;不可用返回 None。

    go2rtc PUT /api/streams:name= 流名、src= 源(单个)——
    若把名字也放进 src,go2rtc 会把名字当媒体源解析而报 source not supported。
    """
    name = f"pb_{printer_id}"
    try:
        async with httpx.AsyncClient(timeout=35) as c:
            await c.put(f"{settings.camera_api}/api/streams",
                        params={"name": name, "src": _SRC.format(host=host)})
            r = await c.get(f"{settings.camera_api}/api/frame.jpeg",
                            params={"src": name})
        if r.status_code == 200 and r.content.startswith(b"\xff\xd8"):
            return r.content
    except httpx.HTTPError:
        pass
    return None
