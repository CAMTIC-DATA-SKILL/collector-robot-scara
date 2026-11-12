# collector-robot-scara

엡손 RC90 Remote Ethernet에 TCP 클라이언트로 붙어 스카라 관절값을 읽는 컬렉터다. `Main.prg`가 밀어 주는 스트림이 아니라, 접속 후 로그인하고 필요할 때마다 `$Execute`로 값을 요청한다.

```
리눅스 엣지                         RC90 (192.168.1.121)
collector-robot-scara ──TCP──▶ Remote Ethernet 서버
        │  $Login
        │  $GetStatus
        │  $Execute,"Print ..."
        ◀── #Login,#GetStatus,#Execute
        │
        └── ZeroMQ ──▶ 게이트웨이
```

북향 토픽은 `collector.robot.{DEVICE_KEY}.{data|health|ack}` 다. cmd 는 로봇으로 넘기지 않고 `E-4102` ack 를 돌려준다.

## 컨트롤러에서 한 번 할 일

RC+ [System Configuration]에서 Remote Ethernet 포트와 비밀번호를 저장하고, 제어 장치를 Remote Ethernet으로 둔다. 이 값은 컨트롤러에 남으므로 수집 중에 윈도우 PC를 켜 둘 필요는 없다.

값을 읽는 명령이 `$Execute`라서 모니터링 전용으로는 부족하다. `$GetStatus`의 Auto, Ready가 켜져 있고 Error, EStop, Safeguard가 꺼져 있어야 Execute가 받아들여진다. SPEL 태스크가 돌고 있으면 Ready가 꺼져 컬렉터는 대기한다.

컨트롤러의 Remote Ethernet timeout은 `POLL_INTERVAL_SEC`보다 길어야 한다. 기본 주기는 1초다.

## 실행

Python 3.10 이상.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

`.env`의 `SOCKET_HOST`, `SOCKET_PORT`, `REMOTE_PASSWORD`를 현장에 맞춘다. 포트 기본값은 5000이다. `Main.prg`의 5002, 5003과는 다른 포트다.

### 서비스 등록 (Linux)

`.venv` 와 `.env` 를 만든 뒤, 프로젝트 루트에서 등록합니다. 유닛은 현재 경로를 기준으로 생성됩니다 (`systemd/*.service` 는 `/opt` 고정 설치 예시).

```bash
sudo bash service_add.sh
journalctl -u collector-robot-scara -f
```

- `/etc/systemd/system` 에 시스템 유닛을 등록하고 `multi-user.target` 으로 부팅 시 자동 기동합니다.
- 실행 계정은 프로젝트 디렉터리 소유자입니다.
- 중지하면 `$Logout` 을 확인한 뒤 소켓을 닫습니다.
- 제거: `sudo systemctl disable --now collector-robot-scara && sudo rm /etc/systemd/system/collector-robot-scara.service && sudo systemctl daemon-reload`

```bash
python script/smoke_socket.py
python -m core.zeromq_client --device-key scara-rc90
```

스모크는 로컬 소켓으로 로그인, 상태 비트, 값마다 `Print`, 따옴표 안의 줄바꿈, 거절 후 세션 유지, 종료 시 `$Logout`, `error=1`이면 `$Reset` 없이 대기를 본다. 마지막 줄이 `== PASS n/n ==` 이면 성공이다.

## 한 주기

1. 소켓이 없으면 컨트롤러에 접속한다.
2. `$Login,비밀번호`를 한 번 보내고 `#Login,0`을 확인한다.
3. `$GetStatus`로 11비트를 읽는다. 순서는 Test, Teach, Auto, Warning, SError, Safeguard, EStop, Error, Paused, Running, Ready다.
4. Execute를 받을 수 있으면 `socket_map.json`의 `executes`를 순서대로 보내고, `#Execute,"..."` 안의 문자열을 쉼표로 이어 붙인다.
5. 칸을 샘플로 만들어 data를 발행한다.

받을 수 없으면 data를 만들지 않고 health만 남긴 뒤 다음 주기에 상태부터 다시 본다. `error=1`도 같다. Execute를 보내지 않고, 에러를 지우지 않은 채 다음 주기에 상태를 다시 본다. 로그인 실패나 끊김은, 로그인되어 있으면 `$Logout`을 확인한 뒤 소켓을 닫고 `RECONNECT_INTERVAL_SEC` 뒤에 다시 붙는다.

## 종료

컬렉터를 끄면 로그인된 세션에 `$Logout`을 보내고 `#Logout,0`을 확인한 다음 소켓을 닫는다. 로그에 `Remote Ethernet 세션을 닫음: $Logout 확인, $Reset 없음`이 남는다. 소켓만 닫으면 컨트롤러에 1504(Remote Ethernet 통신 끊김)가 남는다.

세션을 열 때 `$Reset`은 보내지 않는다. `$Reset`은 통신 에러만 지우는 명령이 아니라 컨트롤러 전체 리셋이다. 걸린 에러와 비상정지를 풀고, 로봇 파라미터를 초기화하며, 일반 출력도 끈다. 서보 이상이나 안전 회로 에러가 있어도 컬렉터가 지우지 않는다. 1504가 지난 테스트에 남아 있으면 RC+나 사람이 한 번 `$Reset`해서 지운다.

## 기본 칸

`socket_map.json`은 값마다 `Print`를 한 번씩 보낸다. `Print` 결과에는 줄바꿈이 들어 있고, 원격 응답은 `#Execute," 176.685\r\n"\r\n`처럼 따옴표 안에 CRLF가 있다. 명령 문자열에는 `$`를 넣지 않는다. `Chr$(44)`는 원격 명령의 `$`와 겹쳐 `!Execute,99`가 된다.

| index | 이름 | SPEL |
| --- | --- | --- |
| 0–3 | `j1_position` … `j4_position` | `Agl(1)` … `Agl(4)` |
| 4–7 | `j1_torque` … `j4_torque` | `RealTorque(1)` … `RealTorque(4)` |
| 8–11 | `x` `y` `z` `rz` | `CX(CurPos)` `CY` `CZ` `CU` |
| 12–13 | `motor_state` `power_mode` | `Motor` `Power` |

`line`은 이어 붙인 원문이다. 상태 비트는 `remote_auto`, `remote_ready`, `remote_running`, `remote_error`, `remote_estop`, `remote_safeguard`, `remote_flags`, `remote_code`로 같이 나간다.

기본 명령은 값을 인쇄하기만 한다. `executes`를 동작 명령으로 바꾸면 로봇이 움직인다.

`CX(CurPos)`나 `Motor`의 출력 형식이 숫자 칸과 다르면 그 포인트만 `error`가 되고 소켓은 유지된다. 그때는 해당 칸의 `type`이나 명령 문자열만 고친다.
