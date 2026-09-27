FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# 官方切片参数包随镜像分发
COPY profiles ./profiles

# P1:在镜像内集成 OrcaSlicer Linux 无头切片引擎,届时切片容器化
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
