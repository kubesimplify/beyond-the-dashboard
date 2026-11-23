FROM python:3.12.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app.py basket.py http_telemetry.py ./
CMD ["python", "app.py"]
