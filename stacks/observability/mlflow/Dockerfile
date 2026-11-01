# MLflow needs psycopg2 (Postgres backend) and boto3 (MinIO/S3 artifacts),
# which the base image ships without — so we build a thin layer on top.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
      "mlflow==3.10.1" \
      "psycopg2-binary==2.9.10" \
      "boto3==1.35.90"

EXPOSE 5000
