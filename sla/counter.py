#!/usr/bin/env python3
import sys
import time
import logging
import signal
import re
from collections import deque
from typing import Optional, Tuple

import requests
from environs import Env
from prometheus_client import start_http_server, Gauge, Counter

SLA_CURRENT_RATIO = Gauge(
    "sla_current_ratio",
    "SLA ratio for the most recent interval (success / total), value in range [0,1]"
)
SLA_WINDOW_RATIO = Gauge(
    "sla_window_ratio",
    "SLA ratio aggregated over the sliding window (average of recent interval ratios), value in range [0,1]"
)
SLA_CALC_TOTAL = Counter(
    "sla_calculation_total",
    "Total number of SLA calculation runs"
)
SLA_PROBER_REQUEST_DURATION_SECONDS = Gauge(
    "sla_prober_request_duration_seconds",
    "Duration in seconds to fetch metrics from the prober"
)

env = Env()
env.read_env()


class Config:
    PROBER_METRICS_URL: str = env("SLA_PROBER_METRICS_URL", "http://oncall-prober:9081/metrics")
    SCRAPE_INTERVAL: int = env.int("SLA_SCRAPE_INTERVAL", 30)
    WINDOW_SIZE: int = env.int("SLA_WINDOW_SIZE", 12)
    METRICS_PORT: int = env.int("SLA_METRICS_PORT", 9091)
    LOG_LEVEL = env.log_level("SLA_LOG_LEVEL", logging.INFO)
    PROBER_SUCCESS_METRIC: str = env("SLA_PROBER_SUCCESS_METRIC", "prober_create_user_scenario_success_total")
    PROBER_FAIL_METRIC: str = env("SLA_PROBER_FAIL_METRIC", "prober_create_user_scenario_success_fail_total")
    PROBER_REQUEST_TIMEOUT: float = env.float("SLA_PROBER_REQUEST_TIMEOUT", 5.0)


def parse_metric_value(metrics_text: str, metric_name: str) -> Optional[float]:
    pattern = re.compile(rf'^{re.escape(metric_name)}(?:\{{[^\}}]*\}})?\s+([0-9.eE+\-]+)\s*$', re.MULTILINE)
    m = pattern.search(metrics_text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None

class SLAClient:
    def __init__(self, config: Config):
        self.config = config
        self.prev_success: Optional[float] = None
        self.prev_fail: Optional[float] = None

        self.window = deque(maxlen=self.config.WINDOW_SIZE)

    def fetch_prober_metrics(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        start = time.perf_counter()
        try:
            resp = requests.get(self.config.PROBER_METRICS_URL, timeout=self.config.PROBER_REQUEST_TIMEOUT)
            duration = time.perf_counter() - start
            SLA_PROBER_REQUEST_DURATION_SECONDS.set(duration)

            if resp.status_code != 200:
                logging.error("Prober returned non-200 status: %s", resp.status_code)
                return None, None, duration

            text = resp.text

            success = parse_metric_value(text, self.config.PROBER_SUCCESS_METRIC)
            fail = parse_metric_value(text, self.config.PROBER_FAIL_METRIC)

            if success is None:
                logging.debug("Success metric '%s' not found in prober metrics", self.config.PROBER_SUCCESS_METRIC)
            if fail is None:
                logging.debug("Fail metric '%s' not found in prober metrics", self.config.PROBER_FAIL_METRIC)

            return success, fail, duration

        except requests.RequestException as err:
            duration = time.perf_counter() - start
            SLA_PROBER_REQUEST_DURATION_SECONDS.set(duration)
            logging.error("Error fetching prober metrics: %s", err)
            return None, None, duration

    @staticmethod
    def _calc_delta(current: float, previous: Optional[float]) -> float:
        if previous is None:
            delta = current if current is not None else 0.0
        else:
            if current is None:
                delta = 0.0
            else:
                delta = current - previous
                if delta < 0:
                    # counter reset
                    delta = current
        if delta < 0:
            delta = 0.0
        return float(delta)

    def compute_sla_interval(self, success_total: Optional[float], fail_total: Optional[float]) -> Optional[float]:
        if success_total is None and fail_total is None:
            logging.warning("Both success and fail totals are missing; skipping SLA computation for this interval")
            return None

        success_val = success_total if success_total is not None else 0.0
        fail_val = fail_total if fail_total is not None else 0.0

        delta_success = self._calc_delta(success_val, self.prev_success)
        delta_fail = self._calc_delta(fail_val, self.prev_fail)

        self.prev_success = success_val
        self.prev_fail = fail_val

        delta_total = delta_success + delta_fail

        if delta_total <= 0:
            logging.info("No prober events in this interval (delta_total=0). Will not append to SLA window.")
            return None

        sla_ratio = delta_success / delta_total
        if sla_ratio < 0:
            sla_ratio = 0.0
        if sla_ratio > 1:
            sla_ratio = 1.0

        return sla_ratio

    def add_to_window(self, sla_ratio: float) -> None:
        self.window.append(sla_ratio)

    def compute_window_sla(self) -> Optional[float]:
        if not self.window:
            return None
        return sum(self.window) / len(self.window)


def setup_logging(level):
    logging.basicConfig(stream=sys.stdout, level=level, format="%(asctime)s %(levelname)s: %(message)s")


def terminate(sig, frame):
    logging.info("Received termination signal. Exiting.")
    sys.exit(0)

def main():
    config = Config()
    setup_logging(config.LOG_LEVEL)

    logging.info("Starting SLA aggregator")
    logging.info("Prober metrics URL: %s", config.PROBER_METRICS_URL)
    logging.info("Scrape interval (s): %s", config.SCRAPE_INTERVAL)
    logging.info("Sliding window size (intervals): %s", config.WINDOW_SIZE)
    logging.info("Exposing metrics on port: %s", config.METRICS_PORT)

    start_http_server(config.METRICS_PORT)

    client = SLAClient(config)

    signal.signal(signal.SIGTERM, terminate)

    while True:
        SLA_CALC_TOTAL.inc()
        success_total, fail_total, req_duration = client.fetch_prober_metrics()

        sla_interval = client.compute_sla_interval(success_total, fail_total)
        if sla_interval is None:
            SLA_CURRENT_RATIO.set(0.0)
            logging.debug("SLA for this interval is undefined (no events); current gauge set to 0. Window unchanged.")
        else:
            SLA_CURRENT_RATIO.set(sla_interval)
            client.add_to_window(sla_interval)
            logging.info("SLA interval ratio: %.4f (success_delta / total_delta)", sla_interval)

        sla_window = client.compute_window_sla()
        if sla_window is None:
            SLA_WINDOW_RATIO.set(0.0)
            logging.debug("SLA window is empty; window gauge set to 0.")
        else:
            SLA_WINDOW_RATIO.set(sla_window)
            logging.info("SLA window ratio (avg of last %d intervals): %.4f", len(client.window), sla_window)

        time.sleep(config.SCRAPE_INTERVAL)


if __name__ == "__main__":
    main()
