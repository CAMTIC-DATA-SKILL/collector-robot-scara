"""소켓 맵을 읽어 포인트 샘플로 만든다."""
import json
import logging
from pathlib import Path

from pydantic import ValidationError

from model.sample_model import Sample
from model.socket_map_model import PointType, SocketMapSettings, SocketPoint

from .exceptions import SocketClientError, SocketErrorCode

logger = logging.getLogger(__name__)


class SocketMap:
    def __init__(self, settings: SocketMapSettings) -> None:
        self.settings = settings

    @classmethod
    def from_json(cls, path: Path) -> "SocketMap":
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}: JSON 파싱 실패: {e}") from e
        try:
            settings = SocketMapSettings.model_validate(raw)
        except ValidationError as e:
            raise ValueError(f"{path}: {e}") from e
        return cls(settings)

    def describe_plan(self) -> str:
        settings = self.settings
        points = ", ".join(_point_label(p) for p in settings.points)
        return (
            f"{settings.framing.value} login+status then {len(settings.executes)} execute, "
            f"read <={settings.max_bytes}B split {settings.delimiter!r}: {points}"
        )

    def parse(self, frame: str) -> list[Sample]:
        """이어 붙인 Execute 결과를 포인트 순서대로 샘플로 만든다.

        칸이 없거나 타입이 안 맞으면 그 점의 error 로 남긴다.
        """
        fields = _split(frame, self.settings.delimiter)
        samples: list[Sample] = []
        for point in self.settings.points:
            try:
                raw = frame if point.index is None else _field(point, fields)
                value = _coerce(point, raw)
            except SocketClientError as e:
                samples.append(_sample(point, value=None, error=e.code.value))
                continue
            samples.append(_sample(point, value=value, error=None))
        logger.debug("frame %r -> %d points", frame, len(samples))
        return samples


def _sample(point: SocketPoint, *, value: int | float | str | bool | None, error: str | None) -> Sample:
    return Sample(addr=point.addr, name=point.name, index=point.index, type=point.type, value=value, error=error)


def _point_label(point: SocketPoint) -> str:
    where = "line" if point.index is None else str(point.index)
    key = point.name if point.addr == point.name else f"{point.name}={point.addr}"
    return f"{key}[{where}]"


def _split(frame: str, delimiter: str) -> list[str]:
    if delimiter == "":
        return frame.split()
    return frame.split(delimiter)


def _field(point: SocketPoint, fields: list[str]) -> str:
    assert point.index is not None
    if point.index >= len(fields):
        raise SocketClientError(SocketErrorCode.FIELD_MISSING, f"{point.name}: index {point.index}, 칸 {len(fields)}개")
    return fields[point.index].strip()


def _coerce(point: SocketPoint, raw: str) -> int | float | str | bool:
    point_type = point.type
    if point_type is PointType.STR:
        return raw
    if point_type is PointType.BOOL:
        return _as_bool(point, raw)
    if point_type is PointType.I64:
        return _scale_int(point, _as_int(point, raw))
    return _scale_float(point, _as_float(point, raw))


def _scale_int(point: SocketPoint, number: int) -> int:
    if point.scale is None:
        return number
    scaled = number * point.scale
    if isinstance(scaled, float) and not scaled.is_integer():
        raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"{point.name}: scale 결과가 정수가 아님")
    return int(scaled)


def _scale_float(point: SocketPoint, number: float) -> float:
    if point.scale is None:
        return number
    return float(number * point.scale)


def _as_bool(point: SocketPoint, raw: str) -> bool:
    text = raw.strip().lower()
    if text in ("1", "true", "on"):
        return True
    if text in ("0", "false", "off"):
        return False
    raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"{point.name}: bool 이 아님 ({raw!r})")


def _as_int(point: SocketPoint, raw: str) -> int:
    try:
        return int(raw.strip(), 10)
    except ValueError as e:
        raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"{point.name}: 정수가 아님 ({raw!r})") from e


def _as_float(point: SocketPoint, raw: str) -> float:
    try:
        return float(raw.strip())
    except ValueError as e:
        raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"{point.name}: 숫자가 아님 ({raw!r})") from e
