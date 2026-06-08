import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


DEFAULT_URL = "http://127.0.0.1:8011/chatnlu/v1"

SMOKE_CASES = [
    {
        "id": "smoke_ac_open",
        "query": "打开空调",
        "expected": {
            "domain": "A",
            "is_safe": True,
            "intents": ["Open_Air_Condition", "Open_AC"],
        },
    },
    {
        "id": "smoke_reject_abuse",
        "query": "你个傻逼",
        "expected": {
            "domain": "D",
            "is_safe": False,
            "intent": "Unknown",
        },
    },
    {
        "id": "smoke_vehicle_faq",
        "query": "胎压报警灯亮了怎么办",
        "expected": {
            "domain": "B",
            "is_safe": True,
            "intent": "Unknown",
        },
    },
    {
        "id": "smoke_chat",
        "query": "讲个笑话",
        "expected": {
            "domain": "C",
            "is_safe": True,
            "intent": "Unknown",
        },
    },
    {
        "id": "smoke_multiturn_ac_higher",
        "query": "再高点",
        "history": [
            {"role": "user", "content": "把空调调到22度"},
            {
                "role": "assistant",
                "content": "已为您将空调温度设置为22度",
                "metadata": {
                    "intent": "Set_Air_Condition_Temperature",
                    "function": "Set_Air_Condition_Temperature",
                    "slots": {"Number": "22"},
                    "domain": "A",
                    "is_safe": True,
                    "rewritten_query": "把空调调到22度",
                    "candidate_intents": [
                        {"intent": "Set_Air_Condition_Temperature", "slots": {"Number": "22"}}
                    ],
                },
            },
        ],
        "expected": {
            "domain": "A",
            "is_safe": True,
            "intents": ["Inc_Air_Condition_Temperature"],
        },
    },
    {
        "id": "smoke_multiturn_volume_louder",
        "query": "再大点",
        "history": [
            {"role": "user", "content": "把音量调到30"},
            {
                "role": "assistant",
                "content": "音量已设置为30",
                "metadata": {
                    "intent": "Set_Sound_Volume",
                    "function": "Set_Sound_Volume",
                    "slots": {"Number": "30"},
                    "domain": "A",
                    "is_safe": True,
                    "rewritten_query": "把音量调到30",
                    "candidate_intents": [
                        {"intent": "Set_Sound_Volume", "slots": {"Number": "30"}}
                    ],
                },
            },
        ],
        "expected": {
            "domain": "A",
            "is_safe": True,
            "intents": ["Inc_Sound_Volume"],
        },
    },
    {
        "id": "smoke_multiturn_window_close_it",
        "query": "关掉它",
        "history": [
            {"role": "user", "content": "打开车窗"},
            {
                "role": "assistant",
                "content": "已为您打开车窗",
                "metadata": {
                    "intent": "Open_Window",
                    "function": "Open_Window",
                    "slots": {},
                    "domain": "A",
                    "is_safe": True,
                    "rewritten_query": "打开车窗",
                    "candidate_intents": [
                        {"intent": "Open_Window", "slots": {}}
                    ],
                },
            },
        ],
        "expected": {
            "domain": "A",
            "is_safe": True,
            "intents": ["Close_Window"],
        },
    },
]


@dataclass
class EvalCase:
    id: str
    source: str
    query: str
    expected: dict[str, Any]
    history: list[dict[str, Any]] = field(default_factory=list)


def configure_console():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def origin_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def wait_until_ready(url: str, proc: subprocess.Popen | None = None, timeout: float = 60.0):
    docs_url = origin_from_url(url) + "/docs"
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


def start_server(repo_root: Path, url: str):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8011
    scratch = repo_root / "scratch"
    scratch.mkdir(exist_ok=True)
    out_log = scratch / f"gemma_eval_server_{port}.out.log"
    err_log = scratch / f"gemma_eval_server_{port}.err.log"
    proc = subprocess.Popen(
        [
            str(repo_root / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "uvicorn",
            "function_call.gemma_nlu_server:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(repo_root),
        stdout=out_log.open("ab"),
        stderr=err_log.open("ab"),
    )
    return proc, out_log, err_log


def parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def extract_query(user_content: str) -> str:
    marker = "最新指令:"
    if marker in user_content:
        return user_content.rsplit(marker, 1)[1].strip()
    return user_content.strip()


def expected_from_assistant(content: str) -> dict[str, Any] | None:
    expected = parse_json_object(content)
    if not expected:
        return None

    normalized = {
        "domain": expected.get("domain"),
        "is_safe": expected.get("is_safe"),
    }
    candidates = expected.get("candidate_intents") or []
    if candidates:
        normalized["intent"] = candidates[0].get("intent")
    else:
        normalized["intent"] = "Unknown"
    return normalized


def load_dataset_cases(path: Path, limit: int, offset: int) -> list[EvalCase]:
    cases: list[EvalCase] = []
    if limit <= 0:
        return cases

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            if line_number <= offset:
                continue
            if len(cases) >= limit:
                break
            if not line.strip():
                continue
            row = json.loads(line)
            messages = row.get("messages", [])
            if len(messages) < 3:
                continue
            query = extract_query(messages[1].get("content", ""))
            expected = expected_from_assistant(messages[2].get("content", ""))
            if not query or not expected:
                continue
            cases.append(EvalCase(
                id=f"{path.name}:{line_number}",
                source=str(path),
                query=query,
                expected=expected,
                history=[],
            ))
    return cases


def load_jsonl_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            cases.append(EvalCase(
                id=str(row.get("id") or f"{path.name}:{line_number}"),
                source=str(path),
                query=row["query"],
                expected=row["expected"],
                history=row.get("history", []),
            ))
    return cases


def normalize_intent_list(expected: dict[str, Any]) -> list[str]:
    if "intents" in expected and isinstance(expected["intents"], list):
        return [str(item) for item in expected["intents"]]
    if expected.get("intent"):
        return [str(expected["intent"])]
    return []


def actual_candidate_intents(actual: dict[str, Any]) -> list[str]:
    candidates = []
    for candidate in actual.get("candidate_intents") or []:
        intent = candidate.get("intent")
        if intent:
            candidates.append(str(intent))
    function = actual.get("function") or actual.get("intent")
    if function and function not in candidates:
        candidates.insert(0, str(function))
    return candidates


def evaluate_case(case: EvalCase, actual: dict[str, Any] | None, error: str | None = None) -> dict[str, Any]:
    expected = case.expected
    checks: dict[str, bool | None] = {
        "request_ok": actual is not None and error is None,
        "domain_match": None,
        "is_safe_match": None,
        "top1_intent_match": None,
        "top5_intent_match": None,
    }

    if actual is not None:
        if expected.get("domain") is not None:
            checks["domain_match"] = actual.get("domain") == expected.get("domain")
        if expected.get("is_safe") is not None:
            checks["is_safe_match"] = actual.get("is_safe") == expected.get("is_safe")

        expected_intents = normalize_intent_list(expected)
        if expected_intents:
            actual_intents = actual_candidate_intents(actual)
            checks["top1_intent_match"] = bool(actual_intents) and actual_intents[0] in expected_intents
            checks["top5_intent_match"] = any(intent in actual_intents[:5] for intent in expected_intents)

    passed = all(value is not False for value in checks.values())
    return {
        "id": case.id,
        "source": case.source,
        "query": case.query,
        "history": case.history,
        "expected": expected,
        "actual": actual,
        "checks": checks,
        "passed": passed,
        "error": error,
    }


def dry_run_case(case: EvalCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "source": case.source,
        "query": case.query,
        "history": case.history,
        "expected": case.expected,
        "actual": None,
        "checks": {
            "request_ok": None,
            "domain_match": None,
            "is_safe_match": None,
            "top1_intent_match": None,
            "top5_intent_match": None,
        },
        "passed": True,
        "error": None,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
    }

    for key in ["request_ok", "domain_match", "is_safe_match", "top1_intent_match", "top5_intent_match"]:
        applicable = [item["checks"][key] for item in results if item["checks"][key] is not None]
        matched = sum(1 for value in applicable if value is True)
        summary[key] = {
            "matched": matched,
            "applicable": len(applicable),
            "rate": round(matched / len(applicable), 4) if applicable else None,
        }
    return summary


def run_eval(url: str, cases: list[EvalCase], timeout: float) -> list[dict[str, Any]]:
    results = []
    with httpx.Client(timeout=timeout) as client:
        for idx, case in enumerate(cases, 1):
            payload = {
                "query": case.query,
                "trace_id": f"eval_{idx}",
                "history": case.history,
            }
            try:
                response = client.post(url, json=payload)
                response.raise_for_status()
                actual = response.json()
                result = evaluate_case(case, actual)
            except Exception as exc:
                result = evaluate_case(case, None, error=str(exc))
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(f"[{idx}/{len(cases)}] {status} {case.id} :: {case.query}")
    return results


def main():
    configure_console()
    parser = argparse.ArgumentParser(description="Evaluate CARdle Gemma NLU against smoke or dataset cases.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--start-server", action="store_true")
    parser.add_argument("--dataset", default="dataset/test.jsonl")
    parser.add_argument("--limit", type=int, default=0, help="Number of dataset cases to include. 0 disables dataset cases.")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--cases", help="Optional JSONL file with {query, expected}.")
    parser.add_argument("--no-smoke", action="store_true", help="Do not include built-in smoke cases.")
    parser.add_argument("--report", default="scratch/gemma_nlu_eval_report.json")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--ready-timeout", type=float, default=120.0)
    parser.add_argument("--dry-run", action="store_true", help="Only load cases and write expected report skeleton.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    cases: list[EvalCase] = []
    if not args.no_smoke:
        cases.extend(EvalCase(
            id=str(row["id"]),
            source="builtin_smoke",
            query=str(row["query"]),
            expected=dict(row["expected"]),
            history=list(row.get("history", [])),
        ) for row in SMOKE_CASES)

    if args.cases:
        cases.extend(load_jsonl_cases(repo_root / args.cases))

    if args.limit > 0:
        cases.extend(load_dataset_cases(repo_root / args.dataset, args.limit, args.offset))

    if not cases:
        print("No evaluation cases selected.")
        return 1

    proc = None
    try:
        if args.start_server and not args.dry_run:
            proc, out_log, err_log = start_server(repo_root, args.url)
            print(f"Started Gemma NLU server. Logs: {out_log}, {err_log}")
            wait_until_ready(args.url, proc=proc, timeout=args.ready_timeout)
        elif not args.dry_run:
            wait_until_ready(args.url, timeout=args.ready_timeout)

        if args.dry_run:
            results = [dry_run_case(case) for case in cases]
        else:
            results = run_eval(args.url, cases, args.timeout)

        report = {
            "metadata": {
                "url": args.url,
                "dataset": args.dataset,
                "limit": args.limit,
                "offset": args.offset,
                "dry_run": args.dry_run,
            },
            "summary": summarize(results),
            "cases": results,
        }

        report_path = repo_root / args.report
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        print(f"Report written to: {report_path}")
        return 0 if args.dry_run or report["summary"]["failed"] == 0 else 2
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
