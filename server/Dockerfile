# 构建上下文为仓库根目录:
#   docker compose build --pull   (compose 中已配置 context: .)
FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/app ./app
# 官方切片参数包随镜像分发
COPY server/profiles ./profiles
# 前端构建产物随镜像分发
# 注意:容器内 main.py 位于 /app/app/main.py,其 parents[2] 是 /(而非 WORKDIR /app),
# 故前端目录须位于 /web/dist 才能被 SPA 回退路由找到
COPY web/dist /web/dist

# 切片引擎:OrcaSlicer Linux V2.4.2(与 orca_cli.py 实测的 CLI 调用形态同版本)。
# AppImage 构建于 Ubuntu 24.04,Debian 13 glibc 向后兼容;
# 用 --appimage-extract 解包免 FUSE,再以 /usr/local/bin/orca-slicer 包装进 PATH
# (QT_QPA_PLATFORM=offscreen 供无头运行,HOME 指到可写目录供其写配置)。
# 升级版本:下载新 AppImage 到 vendor/ 并同步修改文件名。
COPY vendor/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage /tmp/orca.AppImage
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libegl1 libopengl0 libglu1-mesa libglib2.0-0 libxkbcommon0 \
        libdbus-1-3 libfontconfig1 libx11-6 libxext6 libxrender1 \
        libwebkit2gtk-4.1-0 libjavascriptcoregtk-4.1-0 \
        libsm6 libice6 libxcomposite1 libxdamage1 libxfixes3 \
        libxcursor1 libxrandr2 libxi6 libxtst6 libxinerama1 \
    && rm -rf /var/lib/apt/lists/* \
    && chmod +x /tmp/orca.AppImage \
    && cd /opt && /tmp/orca.AppImage --appimage-extract \
    && rm /tmp/orca.AppImage \
    && printf '#!/bin/sh\nexport QT_QPA_PLATFORM=offscreen\nexport HOME=/tmp/orca-home\nexport XDG_RUNTIME_DIR=/tmp/xdg-runtime\nmkdir -p "$HOME" "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"\nexec /opt/squashfs-root/AppRun "$@"\n' \
       > /usr/local/bin/orca-slicer \
    && chmod +x /usr/local/bin/orca-slicer \
    && orca-slicer --help 2>&1 | head -1 || true

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
