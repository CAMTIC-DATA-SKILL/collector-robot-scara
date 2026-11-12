"""게이트웨이로 ProtocolHeaderDTO 를 보내는 PUB 클라이언트."""
import logging

import zmq

from model.protocol_model import ProtocolHeaderDTO

from .base_client import BaseZmqClient
from .exceptions import ZmqClientError, ZmqErrorCode

logger = logging.getLogger(__name__)


class ZmqPubClient(BaseZmqClient):
    """[topic, header_json] multipart PUB."""

    socket_type = zmq.PUB

    def send(self, header: ProtocolHeaderDTO, *, topic: str) -> str:
        payload = header.model_dump_json()
        frames = [topic.encode("utf-8"), payload.encode("utf-8")]
        try:
            self.sock.send_multipart(frames, flags=zmq.NOBLOCK)
        except zmq.Again as e:
            raise ZmqClientError(ZmqErrorCode.TIMEOUT, f"PUB 송신 버퍼 full: {self._target()}") from e
        except zmq.ZMQError as e:
            raise ZmqClientError(ZmqErrorCode.WRITE_FAILED, f"{self._target()}: {e}") from e
        logger.debug("zmq pub [%s] %s", topic, header.msg_type.value)
        return payload
