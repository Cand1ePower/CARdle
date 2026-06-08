import argparse
import json
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import httpx


DEFAULT_URL = "http://127.0.0.1:8011/chatnlu/v1"
DEFAULT_STREAM_URL = "http://127.0.0.1:8011/chatnlu/stream"


def configure_console():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def wait_until_ready(base_url: str, proc: subprocess.Popen | None = None, timeout: float = 60.0):
    docs_url = base_url.rsplit("/", 2)[0] + "/docs"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError("Gemma NLU server exited before becoming ready.")
        try:
            with urllib.request.urlopen(docs_url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {docs_url}")


def start_server(repo_root: Path):
    scratch = repo_root / "scratch"
    scratch.mkdir(exist_ok=True)
    out_log = scratch / "gemma_console_server.out.log"
    err_log = scratch / "gemma_console_server.err.log"
    proc = subprocess.Popen(
        [str(repo_root / ".venv" / "Scripts" / "python.exe"), "function_call/gemma_nlu_server.py"],
        cwd=str(repo_root),
        stdout=out_log.open("ab"),
        stderr=err_log.open("ab"),
    )
    return proc, out_log, err_log


def format_response(data: dict, ascii_only: bool) -> str:
    if ascii_only:
        return json.dumps(data, ensure_ascii=True, indent=2)
    return json.dumps(data, ensure_ascii=False, indent=2)


def stream_response(client: httpx.Client, url: str, payload: dict, ascii_only: bool) -> dict | None:
    final_data = None
    print("\nGemma(raw)> ", end="", flush=True)
    with client.stream("POST", url, json=payload) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            if event.get("type") == "token":
                text = event.get("text", "")
                if ascii_only:
                    text = text.encode("unicode_escape").decode("ascii")
                print(text, end="", flush=True)
            elif event.get("type") == "error":
                print(f"\nStream error: {event.get('error')}")
            elif event.get("type") == "final":
                final_data = event.get("data")

    print("\n\nGemma(final)>")
    if final_data is not None:
        print(format_response(final_data, ascii_only))
    return final_data


def main():
    configure_console()
    parser = argparse.ArgumentParser(description="Interactive console for CARdle Gemma NLU.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Gemma NLU endpoint URL.")
    parser.add_argument("--start-server", action="store_true", help="Start a temporary local 8011 server.")
    parser.add_argument("--stream", action="store_true", help="Use /chatnlu/stream and print chunks as they arrive.")
    parser.add_argument("--ascii", action="store_true", help="Print JSON with unicode escapes.")
    parser.add_argument("--timeout", type=float, default=240.0, help="Request timeout in seconds.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    endpoint_url = DEFAULT_STREAM_URL if args.stream and args.url == DEFAULT_URL else args.url
    proc = None
    if args.start_server:
        proc, out_log, err_log = start_server(repo_root)
        print(f"Starting Gemma NLU server. Logs: {out_log}, {err_log}")
        wait_until_ready(endpoint_url, proc=proc)
    else:
        try:
            wait_until_ready(endpoint_url, timeout=3.0)
        except Exception:
            print("Gemma NLU server is not running.")
            print("Start it with:")
            print(r"  .venv\Scripts\python.exe function_call\gemma_nlu_server.py")
            print("Or run this console with:")
            print(r"  .venv\Scripts\python.exe tools\gemma_console.py --start-server")
            return 1

    print("Gemma NLU console ready. Type q/quit/exit to stop.")
    print("Input natural user text, for example: open AC in Chinese, play music, or a FAQ question.")

    history = []
    try:
        with httpx.Client(timeout=args.timeout) as client:
            while True:
                try:
                    query = input("\nYou> ").strip()
                except EOFError:
                    break
                if query.lower() in {"q", "quit", "exit"}:
                    break
                if not query:
                    continue

                payload = {
                    "query": query,
                    "trace_id": f"console_{uuid.uuid4().hex[:8]}",
                    "history": history[-6:],
                }
                try:
                    if args.stream:
                        data = stream_response(client, endpoint_url, payload, args.ascii)
                    else:
                        resp = client.post(endpoint_url, json=payload)
                        resp.raise_for_status()
                        data = resp.json()
                except Exception as exc:
                    print(f"Request failed: {exc}")
                    continue

                if not args.stream:
                    print("\nGemma>")
                    print(format_response(data, args.ascii))

                if data is not None:
                    history.append({"role": "user", "content": query})
                    history.append({"role": "assistant", "content": data.get("rewritten_query", "")})
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
