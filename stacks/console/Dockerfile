FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir \
      "fastapi==0.118.0" "uvicorn==0.37.0" "httpx==0.28.1" "pyyaml==6.0.2" "python-multipart==0.0.20"
COPY app ./
EXPOSE 7100
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:7100/api/state')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7100"]
