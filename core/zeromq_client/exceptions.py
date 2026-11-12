"""ZeroMQ 클라이언트 예외. 코드 체계는 collector-robot-modbus 와 같다.

  1xxx  연결 (connection)
  2xxx  입출력 (io)
  3xxx  프로토콜 (protocol)
"""
from enum import Enum


class ZmqErrorCode(str, Enum):
    CONNECT_FAILED = "E-1001"
    TIMEOUT = "E-1003"
    READ_FAILED = "E-2001"
    WRITE_FAILED = "E-2002"
    PROTOCOL_ERROR = "E-3001"


class ZmqClientError(Exception):
    def __init__(self, code: ZmqErrorCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}({code.name}) {detail}".rstrip())
