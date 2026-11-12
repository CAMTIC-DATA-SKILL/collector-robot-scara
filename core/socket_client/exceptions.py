"""Remote Ethernet 소켓 예외.

  1xxx  연결 - 재연결하고 다시 로그인한다
  2xxx  칸 없음 (E-2203)
  3xxx  프레임이 깨지면 재연결한다. 컨트롤러가 명령을 거절한 경우는 세션을 유지한다
"""
from enum import Enum


class SocketErrorCode(str, Enum):
    CONNECT_FAILED = "E-1001"
    CONNECTION_CLOSED = "E-1002"
    TIMEOUT = "E-1003"

    FIELD_MISSING = "E-2203"

    PROTOCOL_ERROR = "E-3001"
    NOT_ACCEPTED = "E-3002"

    UNKNOWN = "E-9001"

    @property
    def requires_reconnect(self) -> bool:
        return self in (
            SocketErrorCode.CONNECT_FAILED,
            SocketErrorCode.CONNECTION_CLOSED,
            SocketErrorCode.TIMEOUT,
            SocketErrorCode.PROTOCOL_ERROR,
        )


class SocketClientError(Exception):
    def __init__(self, code: SocketErrorCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}({code.name}) {detail}".rstrip())
