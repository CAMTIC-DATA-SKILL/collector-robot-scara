"""Remote Ethernet 세션 스모크. 장비 없이 로컬 소켓으로 돈다.

    python script/smoke_socket.py
"""
import logging
import socket
import threading

from pydantic import ValidationError

from _smoke import ROOT, SmokeAbort, SmokeRunner, expect
from config import validate_password
from core.socket_client import RemoteClient, SocketClientConfig, SocketClientError, SocketErrorCode, SocketMap
from core.socket_client.protocol import execute_payload, parse_status
from model.socket_map_model import SocketMapSettings

JOINTS = "1.5,-0.25,3,4,0.1,0.2,0.3,0.4"
CARTESIAN = "10,20,30,40,-1,1"
READY = "#GetStatus,00100000001,0000"
TASK_RUNNING = "#GetStatus,00100000000,0000"
ERROR_1504 = "#GetStatus,00100001001,1504"


def main() -> int:
    runner = SmokeRunner("collector-robot-scara")
    try:
        runner.check("scara map loads", _load_map, required=True)
        runner.check("execute limits", _limits)
        runner.check("status bits", _status_bits)
        runner.check("execute payload unwrap", _unwrap)
        runner.check("password rejects a comma", _password)
        robot = FakeController()
        robot.start()
        try:
            runner.check("login, status, two executes", lambda: _session(robot), required=True)
            runner.check("login is once per connection", lambda: _login_once(robot))
            runner.check("not ready skips execute", lambda: _wait_ready(robot))
            runner.check("bad password then good password", lambda: _bad_password(robot))
            runner.check("rejected execute keeps the session", lambda: _rejected(robot))
            runner.check("error 1504 waits without reset", lambda: _error_waits(robot))
            runner.check("shutdown logouts without reset", lambda: _shutdown(robot))
            runner.check("missing column is a point error", _missing_column)
            runner.check("print newline stays inside the quotes", lambda: _embedded_newline(robot))
        finally:
            robot.close()
        runner.check("overlong line reconnects", _overlong)
        runner.check("peer close reconnects", _closed)
    except SmokeAbort:
        pass
    return runner.finish()


def _load_map() -> str:
    socket_map = SocketMap.from_json(ROOT / "socket_map.json")
    expect(len(socket_map.settings.executes), 14)
    expect(len(socket_map.settings.points), 15)
    expect(socket_map.settings.points[1].name, "j1_position")
    expect(socket_map.settings.points[1].index, 0)
    expect(socket_map.settings.points[-1].name, "power_mode")
    for command in socket_map.settings.executes:
        expect(len(command.encode()) <= 256, True)
        expect('"' in command or "$" in command, False)
    return f"{len(socket_map.settings.executes)} commands, {len(socket_map.settings.points)} points"


def _limits() -> str:
    try:
        SocketMapSettings.model_validate({"executes": ['Print "']})
    except ValidationError:
        pass
    else:
        raise AssertionError("따옴표 명령이 통과했다")
    try:
        SocketMapSettings.model_validate({"executes": ["A" * 257]})
    except ValidationError:
        pass
    else:
        raise AssertionError("257바이트 명령이 통과했다")
    return "256B, no quotes"


def _status_bits() -> str:
    ready = parse_status("00100000001,0000")
    expect(ready.accepts_execute, True)
    expect(ready.auto, True)
    expect(ready.ready, True)
    expect(ready.error, False)
    busy = parse_status("00100000000,0517")
    expect(busy.accepts_execute, False)
    expect(busy.auto, True)
    expect(busy.ready, False)
    expect(busy.code, "0517")
    short = parse_status("0100000001,0000")
    expect(short.valid, False)
    expect(short.accepts_execute, False)
    held = parse_status("00100001001,1504")
    expect(held.error, True)
    expect(held.auto, True)
    expect(held.ready, True)
    expect(held.accepts_execute, False)
    expect(held.code, "1504")
    return ready.reason


def _unwrap() -> str:
    expect(execute_payload('"1,2"'), "1,2")
    expect(execute_payload('"0"'), "0")
    expect(execute_payload("0"), None)
    expect(execute_payload(" 12.5"), "12.5")
    return "quoted csv"


def _password() -> str:
    try:
        validate_password("a,b")
    except ValueError:
        pass
    else:
        raise AssertionError("쉼표 비밀번호가 통과했다")
    expect(validate_password(""), "")
    return "empty ok"


def _session(robot: "FakeController") -> str:
    robot.reset()
    socket_map = SocketMap.from_json(ROOT / "socket_map.json")
    client = _client(robot)
    try:
        client.connect()
        client.login(robot.password)
        status, payload = client.poll(socket_map.settings.executes, socket_map.settings.delimiter)
        expect(status is not None and status.accepts_execute, True)
        expect(payload, f"{JOINTS},{CARTESIAN}")
        samples = {sample.name: sample for sample in socket_map.parse(payload or "")}
        expect(samples["j1_position"].value, 1.5)
        expect(samples["j1_torque"].value, 0.1)
        expect(samples["x"].value, 10.0)
        expect(samples["rz"].value, 40.0)
        expect(samples["motor_state"].value, -1.0)
        expect(samples["power_mode"].value, 1.0)
        expect(samples["line"].error, None)
        expect(robot.execute_count, 14)
        return str(samples["j1_position"].value)
    finally:
        client.close()


def _login_once(robot: "FakeController") -> str:
    robot.reset()
    client = _client(robot)
    try:
        client.connect()
        client.login(robot.password)
        client.login(robot.password)
        expect(robot.login_count, 1)
        expect(client.logged_in, True)
        return "1"
    finally:
        client.close()


def _wait_ready(robot: "FakeController") -> str:
    robot.reset(status=TASK_RUNNING)
    socket_map = SocketMap.from_json(ROOT / "socket_map.json")
    client = _client(robot)
    try:
        client.connect()
        client.login(robot.password)
        status, payload = client.poll(socket_map.settings.executes, ",")
        expect(payload, None)
        expect(status.accepts_execute, False)
        expect(robot.execute_count, 0)
        robot.reset(status=READY)
        status, payload = client.poll(socket_map.settings.executes, ",")
        expect(status.accepts_execute, True)
        expect(payload, f"{JOINTS},{CARTESIAN}")
        expect(robot.execute_count, 14)
        return status.flags
    finally:
        client.close()


def _bad_password(robot: "FakeController") -> str:
    robot.reset()
    client = _client(robot)
    try:
        client.connect()
        try:
            client.login("nope")
        except SocketClientError as e:
            expect(e.code, SocketErrorCode.PROTOCOL_ERROR)
            expect("13" in e.detail, True)
        else:
            raise AssertionError("틀린 비밀번호가 통과했다")
        expect(client.logged_in, False)
        client.login(robot.password)
        expect(client.logged_in, True)
        return "13"
    finally:
        client.close()


def _rejected(robot: "FakeController") -> str:
    robot.reset(fail_execute=True)
    socket_map = SocketMap.from_json(ROOT / "socket_map.json")
    client = _client(robot)
    try:
        client.connect()
        client.login(robot.password)
        try:
            client.poll(socket_map.settings.executes, ",")
        except SocketClientError as e:
            expect(e.code, SocketErrorCode.NOT_ACCEPTED)
        else:
            raise AssertionError("거절된 Execute 가 통과했다")
        expect(client.logged_in, True)
        robot.reset(status=READY)
        status, payload = client.poll(socket_map.settings.executes, ",")
        expect(status.accepts_execute, True)
        expect(payload is not None, True)
        return "kept"
    finally:
        client.close()


def _error_waits(robot: "FakeController") -> str:
    robot.reset(status=ERROR_1504)
    client = _client(robot)
    try:
        client.connect()
        client.login(robot.password)
        status, payload = client.poll(["Print 1"], ",")
        expect(payload, None)
        expect(status.accepts_execute, False)
        expect(status.error, True)
        expect(status.code, "1504")
        expect(robot.execute_count, 0)
        expect(_reset_lines(robot), [])
        client.close()
        expect(robot.lines()[-1], "$Logout")
        expect(_reset_lines(robot), [])
        return status.reason
    finally:
        client.close()


def _shutdown(robot: "FakeController") -> str:
    robot.reset()
    client = _client(robot)
    client.connect()
    client.login(robot.password)
    text = _close_and_capture(client)
    expect(client.logged_in, False)
    expect(robot.lines(), [f"$Login,{robot.password}", "$Logout"])
    expect(_reset_lines(robot), [])
    expect("$Logout 확인, $Reset 없음" in text, True)
    try:
        client.get_status()
    except SocketClientError as e:
        expect(e.code, SocketErrorCode.CONNECT_FAILED)
    else:
        raise AssertionError("닫힌 소켓으로 GetStatus 가 나갔다")
    client.close()
    expect(robot.lines().count("$Logout"), 1)
    return "logout"


def _reset_lines(robot: "FakeController") -> list[str]:
    return [line for line in robot.lines() if line.startswith("$Reset")]


def _close_and_capture(client: RemoteClient) -> str:
    log = logging.getLogger(client.__class__.__module__)
    previous = log.level
    buffer: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            buffer.append(record.getMessage())

    sink = _ListHandler(level=logging.INFO)
    log.addHandler(sink)
    log.setLevel(logging.INFO)
    try:
        client.close()
    finally:
        log.removeHandler(sink)
        log.setLevel(previous)
    return "\n".join(buffer)


def _embedded_newline(robot: "FakeController") -> str:
    robot.reset()
    robot.embed_newline = True
    client = _client(robot)
    try:
        client.connect()
        client.login(robot.password)
        value = client.execute("Print Agl(1)")
        expect(value, "176.685")
        return value
    finally:
        client.close()
        robot.embed_newline = False


def _missing_column() -> str:
    socket_map = SocketMap.from_json(ROOT / "socket_map.json")
    samples = {sample.name: sample for sample in socket_map.parse("1.5")}
    expect(samples["j1_position"].value, 1.5)
    expect(samples["j2_position"].error, SocketErrorCode.FIELD_MISSING.value)
    return samples["j2_position"].error or ""


def _overlong() -> str:
    server, port = _serve_once(lambda conn: conn.sendall(b"x" * 300))
    client = RemoteClient(SocketClientConfig(host="127.0.0.1", port=port, timeout=1.0), max_bytes=64)
    try:
        client.connect()
        try:
            client.login("x")
        except SocketClientError as e:
            expect(e.code, SocketErrorCode.PROTOCOL_ERROR)
            return e.code.value
        raise AssertionError("상한 초과가 통과했다")
    finally:
        client.close()
        server.close()


def _closed() -> str:
    server, port = _serve_once(lambda conn: conn.close())
    client = RemoteClient(SocketClientConfig(host="127.0.0.1", port=port, timeout=1.0))
    try:
        client.connect()
        try:
            client.login("x")
        except SocketClientError as e:
            expect(e.code, SocketErrorCode.CONNECTION_CLOSED)
            return e.code.value
        raise AssertionError("끊긴 연결이 통과했다")
    finally:
        client.close()
        server.close()


def _client(robot: "FakeController") -> RemoteClient:
    return RemoteClient(SocketClientConfig(host="127.0.0.1", port=robot.port, timeout=2.0))


def _serve_once(handle) -> tuple[socket.socket, int]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def run() -> None:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        try:
            handle(conn)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    threading.Thread(target=run, daemon=True).start()
    return server, port


class FakeController:
    """$Login, $Logout, $GetStatus, $Execute 에 응답하는 RC90 대역."""

    def __init__(self) -> None:
        self.password = "secret"
        self._status = READY
        self._fail_execute = False
        self.embed_newline = False
        self.login_count = 0
        self.execute_count = 0
        self._commands: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(8)
        self._server.settimeout(0.2)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._server.close()
        self._thread.join(1.0)

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._commands)

    def reset(self, *, status: str = READY, fail_execute: bool = False) -> None:
        with self._lock:
            self._status = status
            self._fail_execute = fail_execute
            self.embed_newline = False
            self.login_count = 0
            self.execute_count = 0
            self._commands.clear()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._session, args=(conn,), daemon=True).start()

    def _session(self, conn: socket.socket) -> None:
        conn.settimeout(2.0)
        pending = b""
        logged = False
        try:
            while not self._stop.is_set():
                while b"\n" not in pending:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    pending += chunk
                index = pending.find(b"\n")
                line = pending[:index].decode().rstrip("\r")
                pending = pending[index + 1 :]
                reply, logged = self._reply(line, logged)
                conn.sendall((reply + "\r\n").encode())
        except OSError:
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _reply(self, line: str, logged: bool) -> tuple[str, bool]:
        with self._lock:
            self._commands.append(line)
            if line.startswith("$Login,"):
                self.login_count += 1
                if line.split(",", 1)[1] != self.password:
                    return "!Login,13", False
                return "#Login,0", True
            if line == "$Logout":
                if not logged:
                    return "!Logout,11", False
                return "#Logout,0", False
            if not logged:
                name = line[1:].split(",", 1)[0] if line.startswith("$") else "Command"
                return f"!{name},11", False
            if line == "$GetStatus":
                return self._status, True
            if line.startswith('$Execute,"') and line.endswith('"'):
                self.execute_count += 1
                if self._fail_execute:
                    return "!Execute,20", True
                command = line[len('$Execute,"') : -1]
                if self.embed_newline and command == "Print Agl(1)":
                    return '#Execute," 176.685\r\n"', True
                value = _execute_value(command)
                if value is None:
                    return "#Execute,0", True
                return f'#Execute,"{value}"', True
            return "!Execute,12", logged


def _execute_value(command: str) -> str | None:
    for key, value in (
        ("RealTorque(4)", "0.4"),
        ("RealTorque(3)", "0.3"),
        ("RealTorque(2)", "0.2"),
        ("RealTorque(1)", "0.1"),
        ("Agl(4)", "4"),
        ("Agl(3)", "3"),
        ("Agl(2)", "-0.25"),
        ("Agl(1)", "1.5"),
        ("CX(CurPos)", "10"),
        ("CY(CurPos)", "20"),
        ("CZ(CurPos)", "30"),
        ("CU(CurPos)", "40"),
        ("Power", "1"),
        ("Motor", "-1"),
    ):
        if key in command:
            return value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
