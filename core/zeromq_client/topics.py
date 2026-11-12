"""ZeroMQ 토픽 조립. collector-robot-modbus / 게이트웨이와 같은 계층을 쓴다.

발행(PUB): collector.robot.{device_key}.{msg_type}   (data / health / ack)
구독(SUB): middleware.gateway.cmd_                   (cmd_r / cmd_w 공통 prefix)
"""
from model.protocol_model import MsgTypeEnum

PUB_TOPIC_ROOT = "collector"
COLLECTOR_KIND = "robot"
CMD_TOPIC_PREFIX = "middleware.gateway.cmd_"


def topic_for(collector_address: str, msg_type: MsgTypeEnum) -> str:
    return f"{PUB_TOPIC_ROOT}.{COLLECTOR_KIND}.{collector_address}.{msg_type.value}"
