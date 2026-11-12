"""모든 환경 변수는 여기서만 읽는다. 저장소 루트의 .env 를 먼저 불러온다 (.env.example 참고).

    from config import settings
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from core.socket_client.config import SocketClientConfig
from core.zeromq_client.config import ZmqConfig

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_str(key: str, default: str) -> str:
    value = os.getenv(key)
    return value.strip() if value is not None and value.strip() else default


def _env_int(key: str, default: int) -> int:
    return int(_env_str(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(_env_str(key, str(default)))


def _env_bool(key: str, default: bool) -> bool:
    return _env_str(key, str(default)).lower() in ("1", "true", "yes", "on")


def _env_password(key: str) -> str:
    value = os.getenv(key)
    if value is None:
        return ""
    return validate_password(value.strip())


def validate_password(password: str) -> str:
    if any(ch in password for ch in ",\"\r\n"):
        raise ValueError("REMOTE_PASSWORD 에 쉼표, 큰따옴표, 줄바꿈을 넣을 수 없다")
    return password


def _as_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


def _env_path(key: str, default: str) -> Path:
    return _as_path(_env_str(key, default))


@dataclass(slots=True)
class Settings:
    log_level: str
    device_key: str
    gateway_address: str
    remote_password: str
    socket_map_file: Path
    poll_interval: float
    reconnect_interval: float
    socket: SocketClientConfig
    zmq: ZmqConfig


def load_settings() -> Settings:
    device_key = _env_str("DEVICE_KEY", "scara-rc90")
    if "." in device_key:
        raise ValueError(f"DEVICE_KEY 에 '.' 는 쓸 수 없다 (토픽 계층 구분자): {device_key!r}")
    sock, zmq = SocketClientConfig(), ZmqConfig()
    return Settings(
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        device_key=device_key,
        gateway_address=_env_str("GATEWAY_ADDRESS", "gateway"),
        remote_password=_env_password("REMOTE_PASSWORD"),
        socket_map_file=_env_path("SOCKET_MAP_FILE", "socket_map.json"),
        poll_interval=_env_float("POLL_INTERVAL_SEC", 1.0),
        reconnect_interval=_env_float("RECONNECT_INTERVAL_SEC", 5.0),
        socket=SocketClientConfig(
            host=_env_str("SOCKET_HOST", sock.host),
            port=_env_int("SOCKET_PORT", sock.port),
            timeout=_env_float("SOCKET_TIMEOUT_SEC", sock.timeout),
        ),
        zmq=ZmqConfig(
            pub_endpoint=_env_str("ZMQ_PUB_ENDPOINT", zmq.pub_endpoint),
            sub_endpoint=_env_str("ZMQ_SUB_ENDPOINT", zmq.sub_endpoint),
            pub_bind=_env_bool("ZMQ_PUB_BIND", zmq.pub_bind),
            sub_bind=_env_bool("ZMQ_SUB_BIND", zmq.sub_bind),
            recv_timeout_ms=_env_int("ZMQ_RECV_TIMEOUT_MS", zmq.recv_timeout_ms),
            linger_ms=_env_int("ZMQ_LINGER_MS", zmq.linger_ms),
        ),
    )


settings = load_settings()
