FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir \
      "fastapi==0.118.0" "uvicorn==0.37.0" \
      "ezdxf==1.4.4" "numpy==2.3.3" "svgpathtools==1.8.0"
COPY src ./
EXPOSE 7120
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:7120/health')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7120"]
