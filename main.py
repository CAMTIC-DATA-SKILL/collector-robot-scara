"""프로젝트 진입점. RC90 Remote Ethernet 에서 관절값을 읽어 ZeroMQ 로 보낸다.

    python main.py

수집 스레드는 연결 → 로그인 → $GetStatus → $Execute → data PUB 을 돈다.
메인 스레드는 게이트웨이 cmd 를 SUB 하고, 아직 처리하지 않는 cmd 에 ack 를 보낸다.
"""
import logging
import signal
import threading
import time
from uuid import uuid4

from pydantic import BaseModel

from config import settings
from core.socket_client import RemoteClient, SocketClientError, SocketMap
from core.socket_client.protocol import status_samples
from core.zeromq_client import ZeroMqClient, ZmqClientError
from model import (
    AckCode,
    MsgAckDTO,
    MsgAckStatusEnum,
    MsgCmdREnum,
    MsgCmdWEnum,
    MsgDataDTO,
    MsgHealthDTO,
    MsgSampleDTO,
    MsgTypeEnum,
    ProtocolHeaderDTO,
    Sample,
)

logger = logging.getLogger("collector")


def now_ms() -> int:
    return int(time.time() * 1000)


def load_socket_map() -> SocketMap:
    path = settings.socket_map_file
    if not path.is_file():
        raise FileNotFoundError(f"소켓 맵 파일이 없습니다: {path}")
    return SocketMap.from_json(path)


def emit(zmq: ZeroMqClient, msg_type: MsgTypeEnum, body: BaseModel, *, gateway_address: str | None = None) -> None:
    header = ProtocolHeaderDTO(
        msg_id=uuid4(),
        gateway_address=gateway_address or settings.gateway_address,
        collector_address=settings.device_key,
        msg_type=msg_type,
        msg_body=body.model_dump(mode="json"),
        timestamp_ms=now_ms(),
    )
    try:
        payload = zmq.send(header)
    except ZmqClientError as e:
        logger.warning("[%s] zmq pub failed: %s", msg_type.value.upper(), e)
        return
    logger.info("[%s] %s", msg_type.value.upper(), payload)


def emit_health(zmq: ZeroMqClient, *, device_ok: bool, reason: str | None = None) -> None:
    body = MsgHealthDTO(
        device_key=settings.device_key, ipc_ok=True, device_ok=device_ok, reason=reason, observed_ms=now_ms()
    )
    emit(zmq, MsgTypeEnum.HEALTH, body)


def emit_data(zmq: ZeroMqClient, samples: list[Sample]) -> None:
    body = MsgDataDTO(
        device_key=settings.device_key,
        sample_ms=now_ms(),
        samples=[MsgSampleDTO.model_validate(sample.model_dump()) for sample in samples],
    )
    emit(zmq, MsgTypeEnum.DATA, body)


def collect(stop: threading.Event, socket_map: SocketMap, zmq: ZeroMqClient) -> None:
    spec = socket_map.settings
    client = RemoteClient(
        settings.socket,
        framing=spec.framing,
        encoding=spec.encoding,
        max_bytes=spec.max_bytes,
    )
    device_ok = False
    last_block: str | None = None
    try:
        while not stop.is_set():
            started = time.monotonic()
            try:
                client.connect()
                client.login(settings.remote_password)
                status, payload = client.poll(spec.executes, spec.delimiter)
                if payload is None:
                    if status.reason != last_block or device_ok:
                        logger.info("Execute 대기: %s", status.reason)
                        emit_health(zmq, device_ok=False, reason=status.reason)
                    last_block = status.reason
                    device_ok = False
                    stop.wait(settings.poll_interval)
                    continue
                samples = socket_map.parse(payload) + status_samples(status)
            except SocketClientError as e:
                logger.error("%s", e)
                reason = e.detail or e.code.value
                emit_health(zmq, device_ok=False, reason=f"{e.code.value} {reason}".strip())
                device_ok = False
                last_block = None
                if e.code.requires_reconnect:
                    client.close()
                    stop.wait(settings.reconnect_interval)
                else:
                    stop.wait(settings.poll_interval)
                continue
            last_block = None
            if not device_ok:
                emit_health(zmq, device_ok=True)
                device_ok = True
            emit_data(zmq, samples)
            stop.wait(max(0.0, settings.poll_interval - (time.monotonic() - started)))
    finally:
        client.close()
        stop.set()


def handle_command(zmq: ZeroMqClient, header: ProtocolHeaderDTO) -> None:
    """cmd_r / cmd_w 는 로봇으로 넘기지 않고 rejected(E-4102) ack 로 응답한다."""
    logger.info("[SUB %s] %s", header.msg_type.value.upper(), header.model_dump_json())
    if header.msg_type is MsgTypeEnum.CMD_R:
        actions = MsgCmdREnum
    elif header.msg_type is MsgTypeEnum.CMD_W:
        actions = MsgCmdWEnum
    else:
        return
    raw_action = header.msg_body.get("action")
    try:
        action = actions(raw_action)
    except ValueError:
        logger.warning("%s action 판별 불가, ack 생략: %r", header.msg_type.value, raw_action)
        return
    body = MsgAckDTO(
        ref_msg_id=header.msg_id,
        device_key=settings.device_key,
        action=action,
        status=MsgAckStatusEnum.REJECTED,
        code=AckCode.CMD_UNSUPPORTED_ACTION,
        reason=AckCode.CMD_UNSUPPORTED_ACTION.name,
    )
    emit(zmq, MsgTypeEnum.ACK, body, gateway_address=header.gateway_address)


def serve_commands(stop: threading.Event, zmq: ZeroMqClient) -> None:
    while not stop.is_set():
        try:
            header = zmq.recv()
        except ZmqClientError as e:
            logger.warning("zmq sub failed: %s", e)
            stop.wait(0.2)
            continue
        if header is None or header.collector_address != settings.device_key:
            continue
        handle_command(zmq, header)


def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    socket_map = load_socket_map()
    logger.info(
        "socket map %s %s:%s\n%s",
        settings.socket_map_file.name,
        settings.socket.host,
        settings.socket.port,
        socket_map.describe_plan(),
    )
    for index, command in enumerate(socket_map.settings.executes, start=1):
        logger.info("execute[%s] (%sB) %s", index, len(command.encode(socket_map.settings.encoding)), command)

    zmq = ZeroMqClient(settings.zmq)
    zmq.connect()
    worker = threading.Thread(target=collect, args=(stop, socket_map, zmq), name="collector", daemon=True)
    worker.start()
    try:
        serve_commands(stop, zmq)
    finally:
        stop.set()
        worker.join(timeout=settings.reconnect_interval + 2.0)
        zmq.close()


if __name__ == "__main__":
    main()
