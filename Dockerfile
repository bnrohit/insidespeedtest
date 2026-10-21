FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && groupadd -g 10001 speedtest \
 && useradd -r -u 10001 -g 10001 speedtest \
 && mkdir -p /data \
 && chown -R speedtest:speedtest /data
COPY app ./app
COPY config ./config
USER 10001
# Listen ONLY on loopback on the host-networked Docker VM.
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080", "--no-proxy-headers", "--workers", "1"]
