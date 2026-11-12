"""ZeroMQ 소켓 하나(PUB/SUB)의 수명주기."""
import logging

import zmq

from .exceptions import ZmqClientError, ZmqErrorCode

logger = logging.getLogger(__name__)


class BaseZmqClient:
    """하위 클래스는 socket_type 을 정하고 필요하면 `_configure_socket` 을 구현한다.

    zmq 소켓은 스레드 안전하지 않으므로 여러 스레드에서 쓰면 호출측에서 락을 잡는다.
    """

    socket_type: int

    def __init__(self, endpoint: str, *, bind: bool, linger_ms: int = 0) -> None:
        self.endpoint = endpoint
        self.bind = bind
        self.linger_ms = linger_ms
        self._sock: zmq.Socket | None = None

    @property
    def sock(self) -> zmq.Socket:
        if self._sock is None:
            raise ZmqClientError(ZmqErrorCode.CONNECT_FAILED, f"소켓 미연결: {self._target()}")
        return self._sock

    def _target(self) -> str:
        return f"{'bind' if self.bind else 'connect'}:{self.endpoint}"

    def connect(self) -> None:
        try:
            self._sock = zmq.Context.instance().socket(self.socket_type)
            self._sock.setsockopt(zmq.LINGER, self.linger_ms)
            self._configure_socket(self._sock)
            if self.bind:
                self._sock.bind(self.endpoint)
            else:
                self._sock.connect(self.endpoint)
        except zmq.ZMQError as e:
            self.close()
            raise ZmqClientError(ZmqErrorCode.CONNECT_FAILED, f"{self._target()}: {e}") from e
        logger.debug("zmq connected: %s type=%s", self._target(), self.socket_type)

    def _configure_socket(self, sock: zmq.Socket) -> None:
        """RCVTIMEO, 구독 토픽 등 소켓 옵션."""

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            sock.close(linger=self.linger_ms)
        except zmq.ZMQError as e:
            logger.debug("zmq close failed: %s", e)
