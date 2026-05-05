from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    cbr_base_url: str = 'https://www.cbr.ru'
    cbr_full_list_url: str = 'https://www.cbr.ru/banking_sector/credit/FullCoList/'
    broker_url: str = 'redis://redis:6379/0'
    result_backend: str = 'redis://redis:6379/1'
    data_dir: Path = Path('/app/data')
    database_url: str = 'postgresql://postgres:postgres@postgres:5432/cbr_reports'
    db_pool_max_size: int = 20
    log_level: str = 'INFO'
    http_timeout_seconds: int = 30
    http_connect_timeout_seconds: int = 10
    http_read_timeout_seconds: int = 30
    http_max_connections: int = 100
    http_max_keepalive_connections: int = 20
    http_max_concurrency: int = 20
    http_per_host_concurrency: int = 8
    http_rps_limit: float = 6.0
    fetch_bank_batch_size: int = 25
    fetch_report_batch_size: int = 30
    aggregate_bank_batch_size: int = 100
    celery_prefetch_multiplier: int = 1
    celery_task_acks_late: bool = True
    celery_result_expires_seconds: int = 3600
    bank_limit: int = 0
    only_ogrn: str = ''
    user_agent: str = 'Mozilla/5.0 (compatible; CBRReportsBot/1.0; +https://www.cbr.ru)'

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / 'raw'

    @property
    def parsed_reports_dir(self) -> Path:
        return self.data_dir / 'parsed' / 'reports'

    @property
    def parsed_banks_dir(self) -> Path:
        return self.data_dir / 'parsed' / 'banks'

    @property
    def manifests_dir(self) -> Path:
        return self.data_dir / 'manifests'


settings = Settings()
