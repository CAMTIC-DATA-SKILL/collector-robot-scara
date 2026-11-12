"""RC90 Remote Ethernet 클라이언트.

접속은 유지하고, 로그인 한 번 뒤에 $GetStatus 와 $Execute 를 주고받는다.
컨트롤러가 값을 밀어 주지 않으므로 한 주기에 명령을 다시 쓴다.
세션을 열 때 $Reset 은 보내지 않는다. 닫을 때는 $Logout 을 확인한 뒤 소켓을 닫는다.
"""
import logging
import socket

from model.socket_map_model import Framing

from .config import SocketClientConfig
from .exceptions import SocketClientError, SocketErrorCode
from .protocol import ControllerStatus, RemoteReply, execute_payload, parse_response, parse_status

logger = logging.getLogger(__name__)

_RECV = 4096


class RemoteClient:
    """수집 스레드 한 곳에서만 쓴다. 줄 경계를 넘는 바이트는 다음 읽기까지 들고 있는다."""

    def __init__(
        self,
        config: SocketClientConfig,
        *,
        framing: Framing = Framing.CRLF,
        encoding: str = "utf-8",
        max_bytes: int = 8192,
    ) -> None:
        if not config.host.strip():
            raise ValueError("SOCKET_HOST 가 비어 있다")
        self.config = config
        self.framing = framing
        self.encoding = encoding
        self.max_bytes = max_bytes
        self._sock: socket.socket | None = None
        self._pending = b""
        self._logged_in = False

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    def connect(self) -> None:
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self.config.host, self.config.port), self.config.timeout)
            sock.settimeout(self.config.timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except TimeoutError as e:
            raise SocketClientError(SocketErrorCode.TIMEOUT, str(e)) from e
        except OSError as e:
            raise SocketClientError(SocketErrorCode.CONNECT_FAILED, str(e)) from e
        self._sock = sock
        self._pending = b""
        self._logged_in = False
        logger.info(
            "Remote Ethernet %s:%s timeout=%.1fs",
            self.config.host,
            self.config.port,
            self.config.timeout,
        )

    def close(self) -> None:
        """로그인된 세션이면 $Logout 응답을 확인한 뒤에 소켓을 닫는다.

        소켓만 닫으면 컨트롤러에 1504 가 남는다. $Reset 은 보내지 않는다.
        $Reset 은 통신 에러만 지우는 명령이 아니라 컨트롤러 전체 리셋이라,
        걸린 에러와 비상정지를 풀고 파라미터를 초기화하며 일반 출력도 끈다.
        """
        confirmed = False
        try:
            confirmed = self._logout()
        finally:
            self._drop_socket()
        if confirmed:
            logger.info("Remote Ethernet 세션을 닫음: $Logout 확인, $Reset 없음")

    def _logout(self) -> bool:
        if self._sock is None or not self._logged_in:
            return False
        try:
            reply = self.request("$Logout")
        except SocketClientError as e:
            logger.warning("Remote Ethernet 세션을 닫음: $Logout 미확인, 1504 가 남을 수 있다: %s", e)
            return False
        finally:
            self._logged_in = False
        if reply.command.lower() != "logout" or not reply.ok or reply.rest not in {"0", ""}:
            detail = reply.rest if reply.ok else f"!{reply.command},{reply.rest}"
            logger.warning("Remote Ethernet 세션을 닫음: $Logout 미확인, 1504 가 남을 수 있다: %s", detail)
            return False
        return True

    def _drop_socket(self) -> None:
        sock, self._sock = self._sock, None
        self._pending = b""
        self._logged_in = False
        if sock is None:
            return
        try:
            sock.close()
        except OSError as e:
            logger.debug("socket close failed: %s", e)

    def login(self, password: str) -> None:
        """$Login 만 보낸다. 남은 에러는 $Reset 으로 지우지 않는다."""
        if self._logged_in:
            return
        reply = self.request(f"$Login,{password}")
        if reply.command.lower() != "login":
            raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"Login 응답이 아님: {reply.command}")
        if not reply.ok or reply.rest != "0":
            detail = reply.rest if reply.ok else f"!{reply.command},{reply.rest}"
            raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, detail)
        self._logged_in = True
        logger.info("Remote Ethernet 로그인됨")

    def poll(self, commands: list[str], delimiter: str) -> tuple[ControllerStatus, str | None]:
        """수신 가능하면 Execute 결과를 이어 붙인다. 아직이면 상태만 돌려준다."""
        status = self.get_status()
        if not status.accepts_execute:
            return status, None
        return status, self.read_executes(commands, delimiter)

    def get_status(self) -> ControllerStatus:
        reply = self.request("$GetStatus")
        self._raise_unless(reply, "GetStatus", reconnect=True)
        return parse_status(reply.rest)

    def read_executes(self, commands: list[str], delimiter: str) -> str:
        parts = [self.execute(command) for command in commands]
        if delimiter == "":
            return " ".join(parts)
        return delimiter.join(parts)

    def execute(self, command: str) -> str:
        if any(ch in command for ch in "\"\r\n"):
            raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, "Execute 명령에 따옴표나 줄바꿈이 있다")
        reply = self.request(f'$Execute,"{command}"')
        self._raise_unless(reply, "Execute", reconnect=False)
        payload = execute_payload(reply.rest)
        if payload is None:
            raise SocketClientError(SocketErrorCode.NOT_ACCEPTED, "Execute 가 값 없이 끝났다")
        return payload.strip()

    def request(self, line: str) -> RemoteReply:
        if line.startswith("$Login"):
            logger.debug(">> $Login")
        else:
            logger.debug(">> %s", line)
        self._send(line)
        raw = self._read_reply()
        logger.debug("<< %s", raw)
        return parse_response(raw)

    def _read_reply(self) -> str:
        """Print 결과는 따옴표 안에 CRLF 를 포함한다. 따옴표가 닫힐 때까지 줄을 잇는다."""
        parts: list[str] = []
        while True:
            parts.append(self._read_line())
            text = "\n".join(parts)
            if text.count('"') % 2 == 0:
                return text

    def _raise_unless(self, reply: RemoteReply, name: str, *, reconnect: bool) -> None:
        if reply.command.lower() != name.lower():
            raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"{name} 응답이 아님: {reply.command}")
        if reply.ok:
            return
        lost = reply.rest == "11"
        code = SocketErrorCode.PROTOCOL_ERROR if reconnect or lost else SocketErrorCode.NOT_ACCEPTED
        if lost:
            self._logged_in = False
        raise SocketClientError(code, f"!{reply.command},{reply.rest}")

    def _send(self, text: str) -> None:
        payload = text.encode(self.encoding)
        ending = _send_ending(self.framing)
        if not payload.endswith(ending):
            payload += ending
        self._write(payload)

    def _write(self, payload: bytes) -> None:
        if self._sock is None:
            raise SocketClientError(SocketErrorCode.CONNECT_FAILED, "소켓이 없다")
        try:
            self._sock.sendall(payload)
        except TimeoutError as e:
            raise SocketClientError(SocketErrorCode.TIMEOUT, str(e)) from e
        except OSError as e:
            raise SocketClientError(SocketErrorCode.CONNECTION_CLOSED, str(e)) from e

    def _read_line(self) -> str:
        while True:
            cut = _cut(self._pending, self.framing)
            if cut is not None:
                raw, self._pending = cut
                try:
                    return raw.decode(self.encoding)
                except UnicodeError as e:
                    raise SocketClientError(SocketErrorCode.PROTOCOL_ERROR, f"디코딩 실패: {e}") from e
            if len(self._pending) >= self.max_bytes:
                raise SocketClientError(
                    SocketErrorCode.PROTOCOL_ERROR, f"줄 끝 없이 {self.max_bytes}바이트를 넘었다"
                )
            self._fill()

    def _fill(self) -> None:
        if self._sock is None:
            raise SocketClientError(SocketErrorCode.CONNECT_FAILED, "소켓이 없다")
        try:
            chunk = self._sock.recv(_RECV)
        except TimeoutError as e:
            raise SocketClientError(SocketErrorCode.TIMEOUT, str(e)) from e
        except OSError as e:
            raise SocketClientError(SocketErrorCode.CONNECTION_CLOSED, str(e)) from e
        if not chunk:
            raise SocketClientError(SocketErrorCode.CONNECTION_CLOSED, "상대가 연결을 닫았다")
        self._pending += chunk


def _send_ending(framing: Framing) -> bytes:
    if framing is Framing.CR:
        return b"\r"
    if framing is Framing.LF:
        return b"\n"
    return b"\r\n"


def _cut(buf: bytes, framing: Framing) -> tuple[bytes, bytes] | None:
    tokens = (b"\n",) if framing is Framing.LF else (b"\r",) if framing is Framing.CR else (b"\r\n", b"\n", b"\r")
    found: list[tuple[int, bytes]] = []
    for token in tokens:
        index = buf.find(token)
        if index >= 0:
            found.append((index, token))
    if not found:
        return None
    index, token = min(found, key=lambda item: (item[0], -len(item[1])))
    return buf[:index], buf[index + len(token) :]
