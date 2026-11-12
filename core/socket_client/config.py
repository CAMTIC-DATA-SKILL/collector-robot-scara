from dataclasses import dataclass


@dataclass(slots=True)
class SocketClientConfig:
    """RC90 Remote Ethernet TCP 접속. 환경 변수 값은 루트 config.py 에서 채운다."""

    host: str = "192.168.1.121"
    port: int = 5000
    timeout: float = 5.0
