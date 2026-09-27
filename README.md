# PrintBridge · 跨品牌一键打印

从模型市场(MakerWorld 等)**一键下载 → 自动切片 → 推送到任意品牌 3D 打印机**。
PC 与手机用同一个 Web 界面(PWA),数据都在你自己家里。

![status](https://img.shields.io/badge/version-0.1.0_MVP-blue)

## 这版能做什么(P0 / MVP)

- 🔍 **搜索 MakerWorld**:关键词 + 排序(相关度/下载/点赞/最新),国内站直连,无需代理
- 📦 **模型库**:从拓竹市场导入设计(自动下载 3MF),或上传本机 3MF/STL/G-code
- 🔪 **自动切片**:复用你电脑上已安装的 **Creality Print / OrcaSlicer** 的无头 CLI,
  内置创想官方 **K2 Plus 全套参数包**(101 种耗材 × 10 种工艺)
- 🖨️ **一键打印**:选模型 → 选版本 → 切片 → 上传 → 启动打印,全程进度实时推送
- 📱 **手机优先**:Vant 移动端界面,可安装为 PWA;打印机遥测(温度/进度)实时显示
- 🔌 **打印机适配**:
  - `creality_ws` —— 创想 K1/K1C/K1 Max/K2/Ender-3 V3(本地 WebSocket,端口 9999)
  - `moonraker` —— Klipper 系(KE / Sonic Pad / ROOT 机 / 各品牌 DIY 机)

## 快速开始(Windows 开发机,零 Docker)

```bash
# 1. 后端
cd server
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. 前端(开发模式可选;生产直接用已构建的 web/dist 由后端托管)
cd web
npm install && npm run build     # 之后刷新 http://<电脑IP>:8000 即可
```

打开 `http://<电脑IP>:8000`(手机同一 WiFi 直连)。

### 配置 MakerWorld 凭证(下载模型需要)

浏览器登录 makerworld.com → F12 → Application → Cookies → 复制 **`token`** 的值
→ 应用「设置」页粘贴保存。平台只把它作为你本人拉取文件的凭证,不托管账号。

### 连接打印机

「打印机」页 → 右上角 ➡ 添加:
- 创想 K 系列:填打印机局域网 IP 即可(默认端口 9999)
- Klipper/Moonraker:IP + 端口 7125(+ API Key)

连不上时先用探测工具诊断(只读、不会触发打印):

```bash
cd server
.venv\Scripts\python -m app.tools.probe_printer --host 192.168.1.50 --adapter creality_ws
.venv\Scripts\python -m app.tools.probe_source --keyword 龙 --region cn
```

## Docker 部署(NAS / 常开主机)

```bash
docker compose up -d    # server + postgres + redis,http://<主机IP>:8000
```

> 切片引擎:容器内暂用宿主机切片或后期内置 OrcaSlicer Linux 版(见 server/Dockerfile 注释);
> 也可让服务器与装有 Creality Print 的电脑共存时通过本机切片模式运行。

## 目录结构

```
printbridge/
├── server/app/
│   ├── sources/      模型源适配(MakerWorld;后续 Printables...)
│   ├── slicing/      切片引擎封装 + 官方参数包注册表
│   ├── printers/     打印机适配(creality_ws / moonraker)+ 遥测管理
│   ├── orchestration/ 一键打印流水线 + 任务队列
│   ├── api/          REST + WebSocket
│   └── tools/        探测工具(打印机协议 / 模型源连通性)
├── server/profiles/  创想官方切片参数包(K2 Plus 0.4 喷嘴全家桶)
├── web/              Vue3 + Vant 移动优先前端(PWA)
└── docs/             协议备忘(逆向协议结论)
```

## 产品路线

| 阶段 | 内容 |
|---|---|
| P0(现在) | 自托管单机版:搜索/下载/切片/一键打印闭环 |
| P1 | 更多机型参数包、Printables 官方 API 源、切片体验优化 |
| P2 | 切片队列横向扩容、多端客户端 |
| P3 | 更多品牌适配、MakerWorld 官方合作 |



## 已知限制(P0)

- 切片指令模板针对 Orca 系 CLI;若你的切片器版本参数不同,在设置页覆盖路径或提 issue
- 创想 K 系列启停指令模板是社区逆向版本,可用探测工具对实机校准(见 tools/probe_printer)
- 远程(外网)控制、摄像头转发:见路线图 P1/P2

## License

自托管版按开源发布(建议 Apache-2.0)。**模型文件版权归原设计者**,
本平台不存储、不二次分发,仅供用户本人授权拉取后打印。
