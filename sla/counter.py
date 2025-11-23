import time
import logging
import requests
from prometheus_client import start_http_server, Gauge
from environs import Env

env = Env()
env.read_env()

PROMETHEUS_URL = env("SLA_PROBER_METRICS_URL", "http://prober:9081/metrics")
SCRAPE_INTERVAL = env.int("SLA_SCRAPE_INTERVAL", 10)
METRICS_PORT = env.int("SLA_METRICS_PORT", 9082)
REQUEST_TIMEOUT = env.float("REQUEST_TIMEOUT", 2.0)

# Основная SLA метрика
SLA_CURRENT_RATIO = Gauge(
    "sla_current_ratio", "Current SLA ratio of successful runs (success / total)"
)

def get_counter_value(metric_name: str) -> float:
    try:
        response = requests.get(PROMETHEUS_URL, timeout=REQUEST_TIMEOUT)
        for line in response.text.splitlines():
            if line.startswith(metric_name):
                return float(line.split()[-1])
    except Exception as e:
        logging.error(f"Error fetching metric {metric_name}: {e}")
    return 0.0

def main():
    logging.basicConfig(level=logging.INFO)
    start_http_server(METRICS_PORT)
    logging.info(f"SLA exporter started on port {METRICS_PORT}")

    while True:
        total = get_counter_value("prober_create_user_scenario_total")
        success = get_counter_value("prober_create_user_scenario_success_total")

        sla_ratio = (success / total) if total > 0 else 0.0
        SLA_CURRENT_RATIO.set(sla_ratio)

        logging.info(f"Current SLA ratio: {sla_ratio:.2f}")
        time.sleep(SCRAPE_INTERVAL)

if __name__ == "__main__":
    main()
