"""게이트웨이 역할로 collector PUB 을 구독해 출력한다. --cmd 를 주면 cmd 를 한 번 보낸다.

예) python -m core.zeromq_client
    python -m core.zeromq_client --device-key robot-rest-1 --cmd cmd_r --action SET_SCAN
"""
import argparse
import signal
import threading
import time
from uuid import uuid4

from config import settings
from model.protocol_model import MsgTypeEnum, ProtocolHeaderDTO

from .pub_client import ZmqPubClient
from .sub_client import ZmqSubClient
from .topics import COLLECTOR_KIND, PUB_TOPIC_ROOT

SLOW_JOINER_WAIT = 0.5


def main() -> None:
    parser = argparse.ArgumentParser(description="ZeroMQ gateway-side echo")
    parser.add_argument("--endpoint", default=settings.zmq.pub_endpoint, help="collector PUB endpoint (connect)")
    parser.add_argument("--device-key", default="", help="omit to listen to every robot collector")
    parser.add_argument("--cmd", choices=[MsgTypeEnum.CMD_R.value, MsgTypeEnum.CMD_W.value])
    parser.add_argument("--action", default="SET_SCAN")
    parser.add_argument("--cmd-endpoint", default=settings.zmq.sub_endpoint, help="gateway PUB endpoint (bind)")
    args = parser.parse_args()

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    prefix = f"{PUB_TOPIC_ROOT}.{COLLECTOR_KIND}.{args.device_key + '.' if args.device_key else ''}"
    sub = ZmqSubClient(args.endpoint, topics=[prefix], recv_timeout_ms=200)
    sub.connect()
    pub = None
    try:
        print(f"listening connect:{args.endpoint} topic={prefix!r} (Ctrl+C 종료)", flush=True)
        if args.cmd:
            pub = ZmqPubClient(args.cmd_endpoint, bind=True)
            pub.connect()
            time.sleep(SLOW_JOINER_WAIT)
            header = ProtocolHeaderDTO(
                msg_id=uuid4(),
                gateway_address=settings.gateway_address,
                collector_address=args.device_key or settings.device_key,
                msg_type=MsgTypeEnum(args.cmd),
                msg_body={"device_key": args.device_key or settings.device_key, "action": args.action, "timeout_ms": 3000},
                timestamp_ms=int(time.time() * 1000),
            )
            pub.send(header, topic=f"middleware.gateway.{args.cmd}")
            print(f"sent bind:{args.cmd_endpoint} {header.model_dump_json()}", flush=True)
        while not stop.is_set():
            header = sub.recv()
            if header is not None:
                print(f"\n[{header.collector_address}.{header.msg_type.value}]", flush=True)
                print(header.model_dump_json(indent=2), flush=True)
    finally:
        sub.close()
        if pub is not None:
            pub.close()


if __name__ == "__main__":
    main()
