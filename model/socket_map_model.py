"""Remote Ethernet 수집 맵.

한 주기마다 $GetStatus 로 수신 가능 여부를 보고, executes 를 순서대로 $Execute 한다.
각 명령의 결과 문자열을 delimiter 로 이어 붙인 뒤 points.index 로 칸을 고른다.
index 를 비우면 이어 붙인 문자열 전체다.
Execute 명령 문자열은 큰따옴표 없이 256바이트 이하여야 한다.
"""
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

_NAME_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
_EXECUTE_LIMIT = 256


class Framing(str, Enum):
    CRLF = "crlf"
    LF = "lf"
    CR = "cr"


class PointType(str, Enum):
    BOOL = "bool"
    I64 = "i64"
    F64 = "f64"
    STR = "str"

    @property
    def numeric(self) -> bool:
        return self in (PointType.I64, PointType.F64)


class SocketPoint(BaseModel):
    """이어 붙인 결과 안의 칸 하나.

    addr 은 샘플에 실리는 조회 키다. 맵에서 비우면 name 과 같다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    addr: str
    index: int | None = None
    type: PointType = PointType.STR
    scale: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_addr(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        addr = data.get("addr")
        if isinstance(addr, str) and addr.strip():
            if addr == addr.strip():
                return data
            filled = dict(data)
            filled["addr"] = addr.strip()
            return filled
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            return data
        filled = dict(data)
        filled["addr"] = name.strip()
        return filled

    @model_validator(mode="after")
    def _check(self) -> "SocketPoint":
        if not self.name or any(ch not in _NAME_CHARS for ch in self.name):
            raise ValueError(f"포인트 이름은 영숫자/_/- 만 쓴다: {self.name!r}")
        if not self.addr or any(ch not in _NAME_CHARS for ch in self.addr):
            raise ValueError(f"{self.name}: 주소는 영숫자/_/- 만 쓴다: {self.addr!r}")
        if self.index is not None and self.index < 0:
            raise ValueError(f"{self.name}: index 는 0 이상")
        if self.scale is not None and not self.type.numeric:
            raise ValueError(f"{self.name}: scale 은 i64 / f64 에만 쓴다")
        return self


class SocketMapSettings(BaseModel):
    """소켓 맵 JSON 최상위. 주소, 포트, 비밀번호는 환경 변수에 둔다."""

    model_config = ConfigDict(extra="forbid")

    framing: Framing = Framing.CRLF
    max_bytes: int = Field(default=8192, ge=1, le=1_000_000)
    encoding: str = "utf-8"
    # 칸 구분자. 빈 문자열이면 공백으로 나눈다. 줄 끝 구분자는 여기 넣지 않는다
    delimiter: str = ","
    executes: list[str] = Field(default_factory=list)
    points: list[SocketPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "SocketMapSettings":
        try:
            sample = "x".encode(self.encoding)
        except LookupError as e:
            raise ValueError(f"알 수 없는 encoding: {self.encoding}") from e
        del sample
        if not self.executes:
            raise ValueError("executes 가 비어 있다")
        for index, command in enumerate(self.executes, start=1):
            if not command or not command.strip():
                raise ValueError(f"executes[{index}] 가 비어 있다")
            if any(ch in command for ch in "\"\r\n"):
                raise ValueError(f"executes[{index}] 에 큰따옴표나 줄바꿈을 넣을 수 없다")
            size = len(command.encode(self.encoding))
            if size > _EXECUTE_LIMIT:
                raise ValueError(
                    f"executes[{index}] 가 {size}바이트다. Remote Ethernet Execute 는 {_EXECUTE_LIMIT}바이트까지다"
                )
        if not self.points:
            self.points.append(SocketPoint(name="line", type=PointType.STR))
        names = [p.name for p in self.points]
        duplicated = sorted({n for n in names if names.count(n) > 1})
        if duplicated:
            raise ValueError(f"포인트 이름 중복: {duplicated}")
        addrs = [p.addr for p in self.points]
        duplicated_addrs = sorted({a for a in addrs if addrs.count(a) > 1})
        if duplicated_addrs:
            raise ValueError(f"포인트 주소 중복: {duplicated_addrs}")
        return self
