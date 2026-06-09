import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
import socketio


DEFAULT_GATEWAY_PORT = 18140
DEFAULT_GEMMA_PORT = 18141
DEFAULT_ARBITRATION_PORT = 18142
DEFAULT_REDIS_PORT = 18143


@dataclass
class ManagedProcess:
    name: str
    proc: subprocess.Popen
    out_log: Path
    err_log: Path


@dataclass
class TurnResult:
    query: str
    expected_intent: str
    expected_slots: dict[str, Any] = field(default_factory=dict)
    frames: list[dict[str, Any]] = field(default_factory=list)
    first_frame_ms: float | None = None
    total_ms: float | None = None
    history_write_ms: float | None = None
    passed: bool = False
    error: str | None = None


def configure_console():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def origin(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def wait_http_ready(url: str, proc: subprocess.Popen | None, timeout: float):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"Process exited before ready: {proc.args}")
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {url}")


def wait_tcp_ready(host: str, port: int, proc: subprocess.Popen | None, timeout: float):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"Process exited before ready: {proc.args}")
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {host}:{port}")


def start_process(repo_root: Path, scratch: Path, name: str, cmd: list[str], env: dict[str, str]) -> ManagedProcess:
    out_log = scratch / f"e2e_{name}.out.log"
    err_log = scratch / f"e2e_{name}.err.log"
    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        env=env,
        stdout=out_log.open("ab"),
        stderr=err_log.open("ab"),
    )
    return ManagedProcess(name=name, proc=proc, out_log=out_log, err_log=err_log)


def stop_processes(processes: list[ManagedProcess]):
    for managed in reversed(processes):
        proc = managed.proc
        if proc.poll() is not None:
            continue
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


async def wait_history_turns(redis_port: int, device_id: str, min_turns: int, timeout: float) -> tuple[list[dict], float | None]:
    key = f"cardle:history:{device_id}"
    client = aioredis.Redis(host="127.0.0.1", port=redis_port, db=0, decode_responses=True, protocol=2)
    started = time.perf_counter()
    try:
        deadline = started + timeout
        while time.perf_counter() < deadline:
            rows = await client.lrange(key, 0, -1)
            if len(rows) >= min_turns:
                turns = [json.loads(row) for row in rows]
                return turns, (time.perf_counter() - started) * 1000
            await asyncio.sleep(0.1)
        rows = await client.lrange(key, 0, -1)
        return [json.loads(row) for row in rows], None
    finally:
        await client.aclose()


async def send_turn(
    sio: socketio.AsyncClient,
    query: str,
    expected_intent: str,
    expected_slots: dict[str, Any] | None,
    response_timeout: float,
) -> TurnResult:
    result = TurnResult(query=query, expected_intent=expected_intent, expected_slots=expected_slots or {})
    done = asyncio.Event()
    started = time.perf_counter()

    async def on_response(data):
        now = time.perf_counter()
        if result.first_frame_ms is None:
            result.first_frame_ms = (now - started) * 1000
        try:
            frame = json.loads(data) if isinstance(data, str) else data
        except Exception:
            frame = {"raw": data}
        result.frames.append(frame)
        status = frame.get("status")
        if status in {0, -1}:
            result.total_ms = (now - started) * 1000
            done.set()

    sio.on("request_nlu", on_response)
    payload = {
        "query": query,
        "trace_id": f"e2e_{uuid.uuid4().hex}",
        "last_answer": "",
    }
    await sio.emit("request_nlu", json.dumps(payload, ensure_ascii=False))

    try:
        await asyncio.wait_for(done.wait(), timeout=response_timeout)
    except asyncio.TimeoutError:
        result.total_ms = (time.perf_counter() - started) * 1000
        result.error = f"Timed out waiting for final frame after {response_timeout}s"

    final_frame = result.frames[-1] if result.frames else {}
    actual_intent = final_frame.get("intent") or final_frame.get("function")
    actual_slots = final_frame.get("slots") or {}
    slots_match = all(str(actual_slots.get(key)) == str(value) for key, value in result.expected_slots.items())
    result.passed = actual_intent == expected_intent and slots_match
    if actual_intent != expected_intent and result.error is None:
        result.error = f"Expected intent {expected_intent}, got {actual_intent}"
    elif not slots_match and result.error is None:
        result.error = f"Expected slots {result.expected_slots}, got {actual_slots}"
    return result


def summarize_latency(turns: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ["first_frame_ms", "total_ms", "history_write_ms"]:
        values = sorted(float(turn[key]) for turn in turns if turn.get(key) is not None)
        if not values:
            summary[key] = None
            continue
        p95_idx = min(len(values) - 1, int(round((len(values) - 1) * 0.95)))
        summary[key] = {
            "avg": round(sum(values) / len(values), 2),
            "max": round(values[-1], 2),
            "p95": round(values[p95_idx], 2),
        }
    return summary


async def run_e2e(args) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    scratch = repo_root / "scratch"
    scratch.mkdir(exist_ok=True)
    python_exe = repo_root / ".venv" / "Scripts" / "python.exe"
    redis_exe = repo_root / "redis" / "redis-server.exe"
    device_id = f"E2E_{uuid.uuid4().hex[:8]}"

    base_env = os.environ.copy()
    base_env.update({
        "PYTHONUTF8": "1",
        "API_KEY": "xxxx-e2e-mock",
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PORT": str(args.redis_port),
        "REDIS_DB": "0",
        "CHATNLU_INFER_URL": f"{origin(args.gemma_port)}/chatnlu/v1",
        "CHATNLU_TIMEOUT": str(args.turn_timeout),
        "ARBITRATION_URL": f"{origin(args.arbitration_port)}/intent-server/v1",
    })

    processes: list[ManagedProcess] = []
    if args.start_stack:
        processes.append(start_process(
            repo_root,
            scratch,
            "redis",
            [str(redis_exe), "--port", str(args.redis_port), "--save", "", "--appendonly", "no", "--loglevel", "warning"],
            base_env,
        ))
        wait_tcp_ready("127.0.0.1", args.redis_port, processes[-1].proc, args.ready_timeout)

        processes.append(start_process(
            repo_root,
            scratch,
            "arbitration",
            [str(python_exe), "-m", "uvicorn", "client.arbitration:app", "--host", "127.0.0.1", "--port", str(args.arbitration_port)],
            base_env,
        ))
        wait_http_ready(f"{origin(args.arbitration_port)}/docs", processes[-1].proc, args.ready_timeout)

        processes.append(start_process(
            repo_root,
            scratch,
            "gemma",
            [str(python_exe), "-m", "uvicorn", "function_call.gemma_nlu_server:app", "--host", "127.0.0.1", "--port", str(args.gemma_port)],
            base_env,
        ))
        wait_http_ready(f"{origin(args.gemma_port)}/docs", processes[-1].proc, args.ready_timeout)

        processes.append(start_process(
            repo_root,
            scratch,
            "gateway",
            [str(python_exe), "-m", "uvicorn", "server:combined_app", "--host", "127.0.0.1", "--port", str(args.gateway_port)],
            base_env,
        ))
        wait_http_ready(f"{origin(args.gateway_port)}/docs", processes[-1].proc, args.ready_timeout)

    sio = socketio.AsyncClient(logger=False, engineio_logger=False, reconnection=False)
    turns: list[TurnResult] = []
    history_snapshot: list[dict] = []
    try:
        await sio.connect(f"{origin(args.gateway_port)}?device_id={device_id}", transports=["websocket"])

        first = await send_turn(
            sio,
            "把空调调到22度",
            "Set_Air_Condition_Temperature",
            {"Number": "22"},
            args.turn_timeout,
        )
        history_snapshot, first.history_write_ms = await wait_history_turns(args.redis_port, device_id, 2, args.history_timeout)
        turns.append(first)

        second = await send_turn(
            sio,
            "再高点",
            "Inc_Air_Condition_Temperature",
            {},
            args.turn_timeout,
        )
        history_snapshot, second.history_write_ms = await wait_history_turns(args.redis_port, device_id, 4, args.history_timeout)
        turns.append(second)
    finally:
        if sio.connected:
            await sio.disconnect()
        if args.start_stack:
            stop_processes(processes)

    turn_dicts = []
    for turn in turns:
        final_frame = turn.frames[-1] if turn.frames else {}
        turn_dicts.append({
            "query": turn.query,
            "expected_intent": turn.expected_intent,
            "expected_slots": turn.expected_slots,
            "actual_intent": final_frame.get("intent") or final_frame.get("function"),
            "actual_slots": final_frame.get("slots") or {},
            "branch": final_frame.get("branch"),
            "status": final_frame.get("status"),
            "first_frame_ms": round(turn.first_frame_ms, 2) if turn.first_frame_ms is not None else None,
            "total_ms": round(turn.total_ms, 2) if turn.total_ms is not None else None,
            "history_write_ms": round(turn.history_write_ms, 2) if turn.history_write_ms is not None else None,
            "passed": turn.passed,
            "error": turn.error,
            "frames": turn.frames,
        })

    report = {
        "metadata": {
            "device_id": device_id,
            "gateway_url": origin(args.gateway_port),
            "gemma_url": f"{origin(args.gemma_port)}/chatnlu/v1",
            "arbitration_url": f"{origin(args.arbitration_port)}/intent-server/v1",
            "redis_port": args.redis_port,
        },
        "summary": {
            "total": len(turn_dicts),
            "passed": sum(1 for turn in turn_dicts if turn["passed"]),
            "failed": sum(1 for turn in turn_dicts if not turn["passed"]),
            "latency_ms": summarize_latency(turn_dicts),
        },
        "turns": turn_dicts,
        "history_snapshot": history_snapshot,
    }

    report_path = repo_root / args.report
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report written to: {report_path}")
    return 0 if report["summary"]["failed"] == 0 else 2


def main():
    configure_console()
    parser = argparse.ArgumentParser(description="Socket.IO E2E multiturn evaluation with latency metrics.")
    parser.add_argument("--gateway-port", type=int, default=DEFAULT_GATEWAY_PORT)
    parser.add_argument("--gemma-port", type=int, default=DEFAULT_GEMMA_PORT)
    parser.add_argument("--arbitration-port", type=int, default=DEFAULT_ARBITRATION_PORT)
    parser.add_argument("--redis-port", type=int, default=DEFAULT_REDIS_PORT)
    parser.add_argument("--report", default="scratch/e2e_multiturn_latency_report.json")
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--turn-timeout", type=float, default=360.0)
    parser.add_argument("--history-timeout", type=float, default=10.0)
    parser.add_argument("--start-stack", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    return asyncio.run(run_e2e(args))


if __name__ == "__main__":
    raise SystemExit(main())
