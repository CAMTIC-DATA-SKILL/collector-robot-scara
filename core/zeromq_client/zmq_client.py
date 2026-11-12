"""게이트웨이 IPC 용 PUB + SUB 파사드."""
import logging
import threading

from model.protocol_model import ProtocolHeaderDTO

from .config import ZmqConfig
from .pub_client import ZmqPubClient
from .sub_client import ZmqSubClient
from .topics import CMD_TOPIC_PREFIX, topic_for

logger = logging.getLogger(__name__)


class ZeroMqClient:
    """collector → gateway: PUB (data / health / ack)
    gateway → collector: SUB (cmd_r / cmd_w)

    PUB 은 수집 스레드, SUB 는 메인 스레드에서 쓴다. 한 락으로 recv 까지 감싸면
    SUB 대기 동안 data PUB 이 멈추므로 소켓마다 락을 따로 둔다.
    """

    def __init__(self, config: ZmqConfig) -> None:
        self.config = config
        self._pub_lock = threading.Lock()
        self._sub_lock = threading.Lock()
        self._pub = ZmqPubClient(config.pub_endpoint, bind=config.pub_bind, linger_ms=config.linger_ms)
        self._sub = ZmqSubClient(
            config.sub_endpoint,
            bind=config.sub_bind,
            linger_ms=config.linger_ms,
            topics=[CMD_TOPIC_PREFIX],
            recv_timeout_ms=config.recv_timeout_ms,
        )

    def connect(self) -> None:
        self._pub.connect()
        try:
            self._sub.connect()
        except Exception:
            self._pub.close()
            raise
        logger.info("ZeroMQ ready pub=%s sub=%s", self._pub._target(), self._sub._target())

    def close(self) -> None:
        with self._pub_lock:
            self._pub.close()
        with self._sub_lock:
            self._sub.close()

    def send(self, header: ProtocolHeaderDTO) -> str:
        topic = topic_for(header.collector_address, header.msg_type)
        with self._pub_lock:
            return self._pub.send(header, topic=topic)

    def recv(self) -> ProtocolHeaderDTO | None:
        with self._sub_lock:
            return self._sub.recv()
