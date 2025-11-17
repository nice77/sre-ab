# Используем официальный Python 3.11 slim
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY counter.py .
ENV SLA_PROBER_METRICS_URL=http://oncall-prober:9081/metrics
ENV SLA_SCRAPE_INTERVAL=30
ENV SLA_WINDOW_SIZE=12
ENV SLA_LOG_LEVEL=INFO
ENV SLA_METRICS_PORT=9091
EXPOSE 9091
CMD ["python", "counter.py"]
