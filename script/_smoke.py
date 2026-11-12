"""스모크 테스트 공통: 저장소 루트를 import 경로에 추가하고 점검 결과를 집계한다."""
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SmokeAbort(Exception):
    """required 점검이 실패해 이후 점검이 의미 없을 때."""


def expect(actual: Any, expected: Any) -> Any:
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")
    return actual


class SmokeRunner:
    def __init__(self, title: str) -> None:
        self.passed = 0
        self.failed: list[str] = []
        print(f"== {title} ==", flush=True)

    def check(self, name: str, fn: Callable[[], Any], required: bool = False) -> Any:
        start = time.monotonic()
        try:
            result = fn()
        except Exception as e:
            self.failed.append(name)
            print(f"[FAIL] {name}: {type(e).__name__}: {e}", flush=True)
            if required:
                raise SmokeAbort(name) from e
            return None
        elapsed_ms = (time.monotonic() - start) * 1000
        self.passed += 1
        suffix = "" if result is None else f" -> {result}"
        print(f"[PASS] {name} ({elapsed_ms:.0f} ms){suffix}", flush=True)
        return result

    def finish(self) -> int:
        total = self.passed + len(self.failed)
        if self.failed:
            print(f"== FAIL {len(self.failed)}/{total}: {', '.join(self.failed)} ==", flush=True)
            return 1
        print(f"== PASS {total}/{total} ==", flush=True)
        return 0
