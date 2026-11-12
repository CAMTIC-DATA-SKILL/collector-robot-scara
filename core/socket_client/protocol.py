"""Epson Remote Ethernet 한 줄 응답을 상태와 값으로 나눈다.

명령은 `$Name,인자` 이고 성공은 `#Name,...`, 거절은 `!Name,코드` 다.
$GetStatus 의 11비트는 Test Teach Auto Warning SError Safeguard EStop Error Paused Running Ready 순이다.
"""
from dataclasses import dataclass

from model.sample_model import Sample
from model.socket_map_model import PointType

from .exceptions import SocketClientError, SocketErrorCode

# Execute 수신 조건에 쓰는 비트. 매뉴얼의 입력 조건과 같다.
_AUTO = 2
_SAFEGUARD = 5
_ESTOP = 6
_ERROR = 7
_RUNNING = 9
_READY = 10
_FLAG_WIDTH = 11


@dataclass(frozen=True, slots=True)
class RemoteReply:
    ok: bool
    command: str
    rest: str


@dataclass(frozen=True, slots=True)
class ControllerStatus:
    flags: str
    code: str

    @property
    def valid(self) -> bool:
        return len(self.flags) >= _FLAG_WIDTH and all(ch in "01" for ch in self.flags[:_FLAG_WIDTH])

    def bit(self, index: int) -> bool:
        if not self.valid:
            return False
        return self.flags[index] == "1"

    @property
    def auto(self) -> bool:
        return self.bit(_AUTO)

    @property
    def ready(self) -> bool:
        return self.bit(_READY)

    @property
    def running(self) -> bool:
        return self.bit(_RUNNING)

    @property
    def error(self) -> bool:
        return self.bit(_ERROR)

    @property
    def estop(self) -> bool:
        return self.bit(_ESTOP)

    @property
    def safeguard(self) -> bool:
        return self.bit(_SAFEGUARD)

    @property
    def accepts_execute(self) -> bool:
        return self.auto and self.ready and not self.error and not self.estop and not self.safeguard

    @property
    def reason(self) -> str:
        if not self.valid:
            return f"flags={self.flags} code={self.code} 상태 비트는 0/1 11자리여야 한다"
        bits = (
            f"auto={int(self.auto)} ready={int(self.ready)} running={int(self.running)} "
            f"error={int(self.error)} estop={int(self.estop)} safeguard={int(self.safeguard)}"
        )
        return f"flags={self.flags[:_FLAG_WIDTH]} code={self.code} {bits}"


def parse_response(line: str) -> RemoteReply:
    text = line.strip()
    if not text or text[0] not in "#!":
        raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"원격 응답이 아님: {text!r}")
    body = text[1:].strip()
    if "," in body:
        command, rest = body.split(",", 1)
    else:
        command, rest = body, ""
    command = command.strip()
    if not command:
        raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"원격 명령 이름이 없다: {text!r}")
    return RemoteReply(ok=text[0] == "#", command=command, rest=rest.strip())


def parse_status(rest: str) -> ControllerStatus:
    parts = [part.strip() for part in rest.split(",")]
    flags = parts[0] if parts and parts[0] else ""
    code = parts[1] if len(parts) > 1 else ""
    return ControllerStatus(flags=flags, code=code)


def execute_payload(rest: str) -> str | None:
    """따옴표 안은 결과 문자열이다. 따옴표 없는 `0` 은 값 없이 끝난 명령이다."""
    text = rest.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    if text == "0":
        return None
    return text


def status_samples(status: ControllerStatus) -> list[Sample]:
    samples = [
        Sample(addr="remote_flags", name="remote_flags", type=PointType.STR, value=status.flags),
        Sample(addr="remote_code", name="remote_code", type=PointType.STR, value=status.code),
    ]
    if not status.valid:
        return samples
    bits = (
        ("remote_auto", status.auto),
        ("remote_ready", status.ready),
        ("remote_running", status.running),
        ("remote_error", status.error),
        ("remote_estop", status.estop),
        ("remote_safeguard", status.safeguard),
    )
    samples.extend(
        Sample(addr=name, name=name, type=PointType.BOOL, value=value) for name, value in bits
    )
    return samples
