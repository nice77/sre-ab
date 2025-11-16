import sys
import logging
import requests
import signal
import time
from datetime import datetime
from environs import Env
import mysql.connector

# Чтение окружения
env = Env()
env.read_env()

# Конфигурация
class Config(object):
    prometheus_api_url = env("PROMETHEUS_API_URL", 'http://localhost:9090')
    scrape_interval = env.int("SCRAPE_INTERVAL", 60)
    log_level = env.log_level("LOG_LEVEL", logging.INFO)
    mysql_host = env("MYSQL_HOST", 'localhost')
    mysql_port = env.int("MYSQL_PORT", 3306)
    mysql_user = env("MYSQL_USER", 'root')
    mysql_password = env("MYSQL_PASS", '1234')
    mysql_db_name = env("MYSQL_DB_NAME", 'sla')


# Работа с MySQL
class Mysql:
    def __init__(self, config: Config) -> None:
        logging.info('Connecting to database')
        self.connection = mysql.connector.connect(
            host=config.mysql_host,
            user=config.mysql_user,
            password=config.mysql_password,
            auth_plugin='mysql_native_password',
            port=config.mysql_port
        )
        self.table_name = 'indicators'
        logging.info('Starting migration')
        cursor = self.connection.cursor()
        cursor.execute('CREATE DATABASE IF NOT EXISTS %s' % (config.mysql_db_name))
        cursor.execute('USE %s' % (config.mysql_db_name))
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name}(
                datetime datetime NOT NULL DEFAULT NOW(),
                name varchar(255) NOT NULL,
                slo float(4) NOT NULL,
                value float(4) NOT NULL,
                is_bad bool NOT NULL DEFAULT false
            )
        """)
        cursor.execute(f"ALTER TABLE {self.table_name} ADD INDEX (datetime)")
        cursor.execute(f"ALTER TABLE {self.table_name} ADD INDEX (name)")
        self.connection.commit()

    def save_indicator(self, name, slo, value, is_bad=False, time=None):
        cursor = self.connection.cursor()
        sql = f"""
            INSERT INTO {self.table_name} (name, slo, value, is_bad, datetime)
            VALUES (%s, %s, %s, %s, %s)
        """
        val = (name, slo, value, int(is_bad), time)
        cursor.execute(sql, val)
        self.connection.commit()


# Работа с Prometheus API
class PrometheusRequest:
    def __init__(self, config: Config) -> None:
        self.prometheus_api_url = config.prometheus_api_url

    def lastValue(self, query, time_, default):
        try:
            response = requests.get(
                self.prometheus_api_url + '/api/v1/query',
                params={'query': query, 'time': time_}
            )
            content = response.json()
            if not content or len(content['data']['result']) == 0:
                return default
            return content['data']['result'][0]['value'][1]
        except Exception as error:
            logging.error(error)
            return default


# Настройка логирования
def setup_logging(config: Config):
    logging.basicConfig(
        stream=sys.stdout,
        level=config.log_level,
        format="%(asctime)s %(levelname)s: %(message)s"
    )


# Основной цикл
def main():
    config = Config()
    setup_logging(config)
    db = Mysql(config)
    prom = PrometheusRequest(config)

    logging.info("Starting SLA checker")

    while True:
        logging.debug("Run prober")
        unixtimestamp = int(time.time())
        date_format = datetime.utcfromtimestamp(unixtimestamp).strftime('%Y-%m-%d %H:%M:%S')

        # Метрика успешных сценариев
        value = prom.lastValue(
            'increase(prober_create_user_scenario_success_total[1m])', unixtimestamp, 0
        )
        value = int(float(value))
        db.save_indicator(
            name='prober_create_user_scenario_success_total',
            slo=1,
            value=value,
            is_bad=value < 1,
            time=date_format
        )

        # Метрика провалов сценариев
        value = prom.lastValue(
            'increase(prober_create_user_scenario_success_fail_total[1m])', unixtimestamp, 100
        )
        value = int(float(value))
        db.save_indicator(
            name='prober_create_user_scenario_success_fail_total',
            slo=0,
            value=value,
            is_bad=value > 0,
            time=date_format
        )

        # Метрика длительности сценария
        value = prom.lastValue(
            'prober_create_user_scenario_duration_seconds', unixtimestamp, 2
        )
        value = float(value)
        db.save_indicator(
            name='prober_create_user_scenario_duration_seconds',
            slo=0.1,
            value=value,
            is_bad=value > 0.1,
            time=date_format
        )

        logging.debug(f"Waiting {config.scrape_interval} seconds for next loop")
        time.sleep(config.scrape_interval)


# Завершение работы
def terminate(signal_received, frame):
    print("Terminating")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, terminate)
    main()
