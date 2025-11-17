FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 9081
ENV SCRAPE_INTERVAL=60
ENV LOG_LEVEL=INFO
CMD ["python", "prober.py"]