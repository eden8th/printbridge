# PrintBridge · 跨品牌一键打印

从模型市场（MakerWorld）**一键下载 → 自动切片 → 推送到任意品牌 3D 打印机**。

一条命令起在自己家里：NAS、常开主机、软路由都行。数据全部留在本机，
没有账号、没有云服务、没有外发流量。

## 功能

- **发现**：搜索 MakerWorld（关键词 + 相关度/下载/点赞/最新排序）
- **链接导入**：粘贴 makerworld.com 或 makerworld.com.cn 的分享链接直接入库。
  两站是**互不相通的 ID 空间**，程序按链接域名选 API 区域；国际站链接会自动
  匹配国内站的镜像条目，从而拿到中文标题与描述
- **模型库**：从拓竹市场导入设计（自动下载 3MF），或上传本机 3MF/STL/G-code
- **自动切片**：内置 **OrcaSlicer 2.4.2** 无头 CLI，随镜像分发创想官方参数包
  （39 个机型包，共 1076 个 JSON，含耗材与工艺配置）
- **一键打印**：选模型 → 选版本 → 切片 → 上传 → 启动打印，进度实时推送（WebSocket）
- **摄像头**：创想 K 系列走私有 WebRTC 协议，由内置 go2rtc sidecar 截帧成 JPEG 下发；
  Moonraker 机型自动发现 `/server/webcams/list`
- **耗材管理**：CFS 多料道换料自动执行，按料道记录克重库存，切片后校验够不够打
- **手机优先**：Vant 移动端界面，可安装为 PWA

### 支持的打印机

| 适配器 | 机型 | 连接方式 |
|---|---|---|
| `creality_ws` | 创想 K1 / K1C / K1 Max / K2 / K2 Pro | 局域网 WebSocket，端口 9999 |
| `moonraker` | Klipper 系（KE / Sonic Pad / ROOT 机 / 各类 DIY 机） | REST + WS，端口 7125 |

## 快速开始（Docker，推荐）

需要 Docker 与 Docker Compose。**不需要预装 Node.js 或 Python**。

```bash
git clone <repo-url> printbridge && cd printbridge

# 1. 准备构建依赖（OrcaSlicer AppImage + go2rtc 二进制，仓库不收录）
python tools/prepare.py

# 2. 起服务（前端在镜像内用 node 阶段构建）
docker compose up -d --build
```

浏览器打开 `http://<主机IP>:8002`。

> `tools/prepare.py` 需要 Python 3.9+，会下载并校验 sha256，版本钉死在
> go2rtc 1.9.14 / OrcaSlicer 2.4.2。

想让「扫描局域网」生效，复制 `.env.example` 为 `.env` 后填
`PB_SCAN_CIDRS=192.168.x.0/24`——容器内只看到 Docker 网桥，不填就只能手动输 IP。
查本机网段：`ip route | grep -o '192\.168\.[0-9]*\.0/24' | head -1`

## 配置 MakerWorld 凭证（下载模型需要）

浏览器登录 makerworld.com → F12 → Application → Cookies → 复制 **`token`** 的值
→ 应用「设置」页粘贴保存。

凭证明文存在你自己的数据库里，只作为你本人拉取文件的凭据，不托管账号、不外发。
设置页也支持直接填账号密码由后端登录，以及一个书签脚本在官网页面上读取 token。

## 连接打印机

「打印机」页 → 添加：

- 创想 K 系列：填打印机局域网 IP 即可（默认端口 9999）
- Klipper/Moonraker：IP + 端口 7125（+ API Key）

连不上先用探测工具诊断（只读、不会触发打印）：

```bash
cd server
python -m app.tools.probe_printer --host 192.168.1.50 --adapter creality_ws
python -m app.tools.probe_source --keyword 龙 --region cn
```

## 开发（Windows / Linux 均可，零 Docker）

```bash
# 后端（Python 3.11+）
cd server
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

开发模式下前端用 Vite 热更新（另开一个终端）：

```bash
cd web && npm install && npm run dev
```

生产模式直接用已构建的 `web/dist`（由后端托管）：

```bash
cd web && npm install && npm run build
```

数据库默认是 SQLite（落在 `server/data/`），开箱即用；compose 里注入的是 PostgreSQL。

## 目录结构

```
printbridge/
├── server/app/
│   ├── sources/       模型源适配(MakerWorld)
│   ├── slicing/       OrcaSlicer CLI 封装 + 官方参数包注册表
│   ├── printers/      打印机适配(creality_ws / moonraker)+ 遥测循环
│   ├── orchestration/ 一键打印流水线 + 进程内任务队列
│   ├── api/           REST + WebSocket
│   ├── services/      设置、摄像头截帧、打印状态监听
│   └── tools/         探测工具(打印机协议 / 模型源连通性)
├── server/profiles/   创想官方切片参数包(1076 个 JSON)
├── web/               Vue3 + Vant 移动优先前端(PWA)
├── tools/prepare.py   构建依赖准备脚本(拉 vendor 二进制)
└── docs/协议备忘.md   逆向协议的实测结论(改适配器前先读)
```

## 已知限制

- **MakerWorld 适配走的是非公开接口**（Bambu Cloud App 同源后端，社区逆向），
  上游改协议即失效。项目不代理、不缓存、不二次分发模型文件，只用你自己的
  token 拉取你有权使用的设计
- **切片指令模板针对 Orca 系 CLI**。若你的切片器版本参数不同，在设置页覆盖路径
- **创想 K 系列的启停指令与摄像头是逆向的私有协议**，只在 K1/K2 系列实机校准过；
  其他机型未验证
- **打印机凭据（Moonraker API Key）与 MakerWorld token 明文存库**。本项目按
  「自托管单机、只跑在可信内网」设计；对外暴露前请自行加密
- **Docker 镜像目前只支持 x86_64**（Dockerfile 的 AppImage 文件名写死 amd64）。
  arm64 需自行改 `server/Dockerfile`
- **摄像头需 `camera` 容器以 host 网络运行**：ICE 候选必须是宿主机 LAN IP，
  bridge 网络的容器地址打印机不可达
- **创想云（Creality Cloud）分享链接暂不支持**，只识别并给出提示
- 没有账号体系，**不要直接暴露到公网**。需要在公网访问就自己在前面加一层
  反向代理 + 认证

## License

[Apache-2.0](LICENSE)。**模型文件版权归原设计者**，本项目不存储、不二次分发
模型文件，仅供用户本人授权拉取后打印。