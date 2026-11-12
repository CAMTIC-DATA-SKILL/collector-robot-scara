"""소켓 읽기 결과."""
from pydantic import BaseModel, ConfigDict

from .socket_map_model import PointType

Value = int | float | str | bool | None


class Sample(BaseModel):
    """포인트 한 건. addr 이 게이트웨이 조회 키다. 실패하면 value 는 None, error 에 SocketErrorCode 값."""

    model_config = ConfigDict(frozen=True)

    addr: str
    name: str
    index: int | None = None
    type: PointType
    value: Value | None = None
    error: str | None = None
