"""게이트웨이 cmd 를 받는 SUB 클라이언트."""
import logging

import zmq
from pydantic import ValidationError

from model.protocol_model import ProtocolHeaderDTO

from .base_client import BaseZmqClient
from .exceptions import ZmqClientError, ZmqErrorCode

logger = logging.getLogger(__name__)


class ZmqSubClient(BaseZmqClient):
    """[topic, header_json] multipart SUB. 타임아웃이면 None."""

    socket_type = zmq.SUB

    def __init__(
        self,
        endpoint: str,
        *,
        bind: bool = False,
        linger_ms: int = 0,
        topics: list[str] | None = None,
        recv_timeout_ms: int = 100,
    ) -> None:
        super().__init__(endpoint, bind=bind, linger_ms=linger_ms)
        self.topics = topics or [""]
        self.recv_timeout_ms = recv_timeout_ms

    def _configure_socket(self, sock: zmq.Socket) -> None:
        sock.setsockopt(zmq.RCVTIMEO, self.recv_timeout_ms)
        for topic in self.topics:
            sock.setsockopt_string(zmq.SUBSCRIBE, topic)

    def recv(self) -> ProtocolHeaderDTO | None:
        try:
            frames = self.sock.recv_multipart()
        except zmq.Again:
            return None
        except zmq.ZMQError as e:
            raise ZmqClientError(ZmqErrorCode.READ_FAILED, f"{self._target()}: {e}") from e

        if len(frames) < 2:
            raise ZmqClientError(ZmqErrorCode.PROTOCOL_ERROR, f"multipart 프레임 부족: {len(frames)}")
        try:
            header = ProtocolHeaderDTO.model_validate_json(frames[-1])
        except ValidationError as e:
            raise ZmqClientError(ZmqErrorCode.PROTOCOL_ERROR, f"ProtocolHeaderDTO 파싱 실패: {e}") from e

        logger.debug("zmq sub [%s] %s", frames[0].decode("utf-8", errors="replace"), header.msg_type.value)
        return header
