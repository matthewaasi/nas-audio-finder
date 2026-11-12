FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 MEDIA_ROOT=/music CONFIG_ROOT=/config PUID=99 PGID=100
LABEL org.opencontainers.image.version="2.1.0"
WORKDIR /app
COPY app.py /app/app.py
COPY library.py /app/library.py
COPY authenticity.py /app/authenticity.py
COPY static /app/static
COPY container_entrypoint.py /app/container_entrypoint.py
RUN mkdir -p /music /config
EXPOSE 8080
VOLUME ["/config"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request,urllib.error; r=urllib.request.Request('http://127.0.0.1:8080/api/state'); exec('try:\n urllib.request.urlopen(r,timeout=3)\nexcept urllib.error.HTTPError as e:\n assert e.code == 401')"
ENTRYPOINT ["python", "/app/container_entrypoint.py"]
