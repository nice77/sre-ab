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
    "prober_create_user_scenario_success_total", "Total count of success runs the create user scenario"
)
PROBER_CREATE_USER_SCENARIO_SUCCESS_FAIL_TOTAL = Counter(
    "prober_create_user_scenario_success_fail_total", "Total count of failed runs the create user schema"
)
PROBER_CREATE_USER_SCENARIO_DURATION_SECONDS = Gauge(
    "prober_create_user_scenario_duration_seconds", "Duration in seconds of runs the create user scenario"
)
env = Env()
env.read_env()
class Config(object):
    oncall_exporter_api_url = env("ONCALL_EXPORTER_API_URL")
    oncall_exporter_scrape_interval = env.int("ONCALL_EXPORTER_SCRAPE_INTERVAL", 30)
    oncall_exporter_log_level = env.log_level("ONCALL_EXPORTER_LOG_LEVEL", logging.INFO)
    oncall_exporter_metrics_port = env.int("ONCALL_EXPORTER_METRICS_PORT", 9081)

class OncallProberClient:
    def __init__(self, config: Config) -> None:
        self.oncall_api_url = config.oncall_exporter_api_url
    def probe(self) -> None:
        PROBER_CREATE_USER_SCENARIO_TOTAL.inc()
        logging.debug("try create user")
        username = 'test_prober_user'
        start = time.perf_counter()
        create_request = None
        try:
            create_request = requests.post('%s/users' % (self.oncall_api_url), json={
                "name": username
            })
        except Exception as err:
            logging.debug(err)
            PROBER_CREATE_USER_SCENARIO_SUCCESS_FAIL_TOTAL.inc()
        finally:
            try:
                delete_request = requests.delete(
                '%s/users/%s' % (self.oncall_api_url, username))
            except Exception as err:
                logging.debug(err)
        if create_request and create_request.status_code == 200 and delete_request.status_code == 200:
            logging.debug("all good")
            PROBER_CREATE_USER_SCENARIO_SUCCESS_TOTAL.inc()
        else:
            logging.debug("script failed")
            PROBER_CREATE_USER_SCENARIO_SUCCESS_FAIL_TOTAL.inc()
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
    logging.info("Creating a client")
    client = OncallProberClient(config)
    logging.info("Client create success")
    while True:
        logging.debug(f"Run prober")
        client.probe()
        logging.debug(f"Waiting {config.oncall_exporter_scrape_interval} seconds for next loop")
        time.sleep(config.oncall_exporter_scrape_interval)

def terminate(signal, frame):
    print("Terminating")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, terminate)
    main()
