# syntax=docker/dockerfile:1.7
# Pin by digest; renovate/dependabot can keep it current.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    XDG_CACHE_HOME=/opt/models \
    HF_HOME=/opt/models \
    SANITIZER_MAX_UPLOAD_BYTES=104857600 \
    SANITIZER_MAX_PAGES=500 \
    SANITIZER_LOW_CONFIDENCE_THRESHOLD=0.65

# libgl1/libglib2.0-0: opencv-headless (rapidocr)
# libgomp1: onnxruntime OpenMP runtime
# libmagic1: python-magic
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -u 10001 -m -s /sbin/nologin app

WORKDIR /app
COPY requirements.txt ./

# CPU-only torch first — otherwise pip pulls the CUDA wheel (~2.5 GB)
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.4.1" \
 && pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt \
 && pip check


# Warm RapidOCR + Docling model caches into a shared, app-readable path.
# NOTE: rapidocr-onnxruntime was renamed to rapidocr; onnxruntime must be
# installed explicitly (rapidocr >=2.0.6 does not bundle it).
RUN mkdir -p /opt/models \
 && python -c "from rapidocr import RapidOCR; RapidOCR()" \
 && python -c "from docling.document_converter import DocumentConverter; DocumentConverter()" \
 && chown -R app:app /opt/models
COPY --chown=app:app app/ ./app/

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=3).status==200 else 1)"

# Single worker by design: the ingest pipeline is serialized per-process by
# app.main._ingest_lock. Do not raise --workers or run multiple replicas
# without replacing that lock with a distributed primitive.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-graceful-shutdown", "120", \
     "--no-server-header"]