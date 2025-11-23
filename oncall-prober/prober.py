import sys
import logging
import requests
import signal
import time
from environs import Env
from prometheus_client import start_http_server, Gauge, Counter

PROBER_CREATE_USER_SCENARIO_TOTAL = Counter(
    "prober_create_user_scenario_total", "Total count of runs the create user scenario to oncall API"
)
PROBER_CREATE_USER_SCENARIO_SUCCESS_TOTAL = Counter(
    "prober_create_user_scenario_success_total", "Total count of successful runs the create user scenario"
)
PROBER_CREATE_USER_SCENARIO_SUCCESS_FAIL_TOTAL = Counter(
    "prober_create_user_scenario_success_fail_total", "Total count of failed runs the create user scenario"
)
PROBER_CREATE_USER_SCENARIO_DURATION_SECONDS = Gauge(
    "prober_create_user_scenario_duration_seconds", "Duration in seconds of runs the create user scenario"
)

env = Env()
env.read_env()

class Config:
    oncall_exporter_api_url = env("ONCALL_EXPORTER_API_URL")
    oncall_exporter_scrape_interval = env.int("ONCALL_EXPORTER_SCRAPE_INTERVAL", 5)
    oncall_exporter_log_level = env.log_level("ONCALL_EXPORTER_LOG_LEVEL", logging.INFO)
    oncall_exporter_metrics_port = env.int("ONCALL_EXPORTER_METRICS_PORT", 9081)
    request_timeout = env.float("REQUEST_TIMEOUT", 2.0)

class OncallProberClient:
    def __init__(self, config: Config) -> None:
        self.oncall_api_url = config.oncall_exporter_api_url
        self.timeout = config.request_timeout

    def probe(self) -> None:
        PROBER_CREATE_USER_SCENARIO_TOTAL.inc()
        username = 'test_prober_user'
        start = time.perf_counter()
        success = False

        try:
            create_request = requests.post(
                f'{self.oncall_api_url}/users', json={"name": username}, timeout=self.timeout
            )
            if create_request.status_code == 200:
                delete_request = requests.delete(
                    f'{self.oncall_api_url}/users/{username}', timeout=self.timeout
                )
                if delete_request.status_code == 200:
                    success = True
        except Exception as e:
            logging.debug(f"Probe error: {e}")

        if success:
            PROBER_CREATE_USER_SCENARIO_SUCCESS_TOTAL.inc()
            logging.debug("Scenario succeeded")
        else:
            PROBER_CREATE_USER_SCENARIO_SUCCESS_FAIL_TOTAL.inc()
            logging.debug("Scenario failed")

        duration = time.perf_counter() - start
        PROBER_CREATE_USER_SCENARIO_DURATION_SECONDS.set(duration)

def setup_logging(config: Config):
    logging.basicConfig(
        stream=sys.stdout,
        level=config.oncall_exporter_log_level,
        format="%(asctime)s %(levelname)s:%(message)s"
    )

def main():
    config = Config()
    setup_logging(config)
    logging.info(f"Starting prober exporter on port: {config.oncall_exporter_metrics_port}")
    start_http_server(config.oncall_exporter_metrics_port)
    client = OncallProberClient(config)

    while True:
        client.probe()
        time.sleep(config.oncall_exporter_scrape_interval)

def terminate(signal_num, frame):
    print("Terminating")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, terminate)
    main()
