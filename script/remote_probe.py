"""Remote Ethernet에 로그인하고 상태를 읽은 뒤 반드시 $Logout 한다.

소켓을 그대로 닫으면 컨트롤러에 1504가 남는다.

    python script/remote_probe.py
    python script/remote_probe.py --reset
"""
import argparse
import socket

HOST = "192.168.1.121"
PORT = 5000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="로그인 뒤에 $Reset 을 한 번 보낸다")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--password", default="", help="비우면 $Login, 으로 보낸다")
    args = parser.parse_args()

    with socket.create_connection((args.host, args.port), timeout=3) as sock:
        sock.settimeout(3)

        def cmd(line: str) -> bytes:
            sock.sendall((line + "\r\n").encode())
            return sock.recv(256)

        logged_in = False
        try:
            reply = cmd(f"$Login,{args.password}")
            print(reply)
            logged_in = reply.startswith(b"#Login,0")
            if args.reset and logged_in:
                print(cmd("$Reset"))
            print(cmd("$GetStatus"))
        finally:
            if logged_in:
                try:
                    print(cmd("$Logout"))
                except OSError as e:
                    print(f"logout failed: {e}")


if __name__ == "__main__":
    main()
