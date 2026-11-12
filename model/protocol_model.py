"""게이트웨이 ↔ collector 프로토콜 DTO. collector-robot-soket 과 같은 헤더를 쓴다.

ZeroMQ multipart [topic, ProtocolHeaderDTO JSON].
data 본문의 samples 는 Remote Ethernet 응답에서 뽑은 칸이다. 조회 키는 addr 이고 sockets 는 항상 빈 목록이다.
"""
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from .sample_model import Value
from .socket_map_model import PointType


class MsgTypeEnum(str, Enum):
    CMD_R = "cmd_r"
    CMD_W = "cmd_w"
    ACK = "ack"
    HEALTH = "health"
    DATA = "data"


class MsgCmdREnum(str, Enum):
    SET_SCAN = "SET_SCAN"
    SET_DEVICE = "SET_DEVICE"
    READ_ONCE = "READ_ONCE"
    STOP = "STOP"


class MsgCmdWEnum(str, Enum):
    CONTROL_COMMAND = "CONTROL_COMMAND"
    INSERT = "INSERT"


class MsgAckStatusEnum(str, Enum):
    OK = "ok"
    REJECTED = "rejected"
    ERROR = "error"


class AckCode(str, Enum):
    OK = "S-0000"
    CMD_BODY_INVALID = "E-4101"
    CMD_UNSUPPORTED_ACTION = "E-4102"


class ProtocolHeaderDTO(BaseModel):
    msg_id: UUID
    gateway_address: str
    collector_address: str
    msg_type: MsgTypeEnum
    msg_body: dict
    timestamp_ms: int


class MsgAckDTO(BaseModel):
    ref_msg_id: UUID
    device_key: str
    action: MsgCmdREnum | MsgCmdWEnum
    status: MsgAckStatusEnum
    code: AckCode = AckCode.OK
    reason: str | None = None
    applied_ms: int | None = None


class MsgHealthDTO(BaseModel):
    device_key: str
    ipc_ok: bool
    device_ok: bool
    reason: str | None = None
    observed_ms: int


class MsgSampleDTO(BaseModel):
    """게이트웨이 조회 키는 addr. index 는 프레임 칸이라 미들웨어는 읽지 않는다."""

    addr: str
    name: str
    index: int | None = None
    type: PointType
    value: Value | None = None
    error: str | None = None


class MsgDataDTO(BaseModel):
    device_key: str
    sample_ms: int
    samples: list[MsgSampleDTO]
    sockets: list[dict] = Field(default_factory=list)
