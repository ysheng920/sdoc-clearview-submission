"""Full 520-case decision benchmark for Gemini and Jev.

The benchmark measures the shared task both models support: routing an
incoming shipping-operations email into one of five categories. It sends the
email subject/body and attachment file names, never attachment contents.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "benchmarks" / "results"
CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
CATEGORY_CRITERIA = {
    "BL_COMPARISON": (
        "The sender asks to compare or verify a Shipping Instruction against a draft Bill of Lading, "
        "or sends a short conversational request asking the documentation team to prepare, send, issue, "
        "or chase a draft BL for checking. Do not use this category when the email itself contains a "
        "detailed Shipping Instruction; that remains SI_REQUEST even if it ends by asking for a draft BL."
    ),
    "SI_REQUEST": (
        "The sender asks to create or issue a new Shipping Instruction for a specific shipment, or "
        "submits a detailed Shipping Instruction in the email body for processing. A detailed inline SI "
        "remains SI_REQUEST when it ends with a routine request to return a draft BL later."
    ),
    "INVOICE_QUERY": "The sender asks about an invoice, billing, freight, payment, demurrage, detention, THC, or local charges.",
    "GENERAL": (
        "Shipping-related administration, acknowledgement, reminder, SLA notice, or broadcast that "
        "does not request one of the specific actions above."
    ),
    "SPAM": "Unrelated marketing, phishing, promotional, or irrelevant content.",
}


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_cases(limit: int | None = None) -> list[dict]:
    truth = json.loads((ROOT / "data" / "ground_truth.json").read_text(encoding="utf-8"))
    cases = []
    for path in sorted((ROOT / "data" / "inbox").glob("*.json")):
        email = json.loads(path.read_text(encoding="utf-8"))
        email_id = email["email_id"]
        if email_id not in truth:
            continue
        cases.append({
            "id": email_id,
            "subject": email.get("subject", ""),
            "sender": email.get("from", ""),
            "body": (email.get("body") or "")[:3000],
            "attachments": [Path(value).name for value in (email.get("attachments") or [])],
            "truth": truth[email_id]["category"],
        })
        if limit and len(cases) >= limit:
            break
    return cases


def request_json(url: str, key: str, payload: dict, attempts: int = 4) -> tuple[dict, float]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://sdoc-clearview.local",
                "X-Title": "SDOC Clearview Model Benchmark",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8")), (time.perf_counter() - started) * 1000
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"HTTP {exc.code}: {detail}")
            if exc.code not in {408, 429, 500, 502, 503, 529}:
                break
        except (TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(2 ** attempt)
    raise RuntimeError(str(last_error))


def extract_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1]
        clean = clean.rsplit("```", 1)[0]
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        start, end = clean.find("{"), clean.rfind("}")
        if start >= 0 and end > start:
            return json.loads(clean[start:end + 1])
        raise


def batches(items: list[dict], size: int) -> list[list[dict]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def jev_batch(batch: list[dict], key: str) -> dict:
    records = [{key: value for key, value in item.items() if key != "truth"} for item in batch]
    criteria = dict(CATEGORY_CRITERIA)
    questions = {
        item["id"]: {
            "type": "choice",
            "instructions": f'Classify the primary operational intent of the record whose id is "{item["id"]}".',
            "criteria": criteria,
        }
        for item in batch
    }
    response, elapsed = request_json(
        "https://openrouter.ai/api/alpha/decisions",
        key,
        {"model": "typesafe/jev-1.13", "state": {"records": records}, "questions": questions},
    )
    predictions = {}
    for item in batch:
        answer = response.get("answers", {}).get(item["id"], {})
        predictions[item["id"]] = {
            "prediction": str(answer.get("choice", "")).upper(),
            "confidence": answer.get("confidence"),
            "probabilities": answer.get("probabilities"),
        }
    return {
        "predictions": predictions,
        "elapsed_ms": elapsed,
        "usage": response.get("usage", {}),
        "resolved_model": response.get("model"),
        "provider": response.get("provider"),
    }


def chat_prompt(batch: list[dict]) -> str:
    labels = "\n".join(f"- {key}: {value}" for key, value in CATEGORY_CRITERIA.items())
    records = [{key: value for key, value in item.items() if key != "truth"} for item in batch]
    return (
        "Classify every shipping-operations email below. Use exactly one allowed category per record. "
        "Return only a JSON object whose keys are the record ids and whose values are objects with "
        '"category" and numeric "confidence" from 0 to 1. Do not omit any record.\n\n'
        f"Allowed categories:\n{labels}\n\nRecords:\n{json.dumps(records, ensure_ascii=False)}"
    )


def chat_batch(batch: list[dict], *, provider: str, model: str, key: str) -> dict:
    if provider == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        extra = {}
    else:
        url = "https://openrouter.ai/api/v1/chat/completions"
        extra = {"reasoning": {"enabled": False}}
    response, elapsed = request_json(
        url,
        key,
        {
            "model": model,
            "messages": [{"role": "user", "content": chat_prompt(batch)}],
            "temperature": 0,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
            **extra,
        },
    )
    content = response["choices"][0]["message"].get("content") or ""
    parsed = extract_json(content)
    predictions = {}
    for item in batch:
        value = parsed.get(item["id"], {})
        if isinstance(value, str):
            value = {"category": value}
        predictions[item["id"]] = {
            "prediction": str(value.get("category", "")).upper(),
            "confidence": value.get("confidence"),
            "probabilities": None,
        }
    return {
        "predictions": predictions,
        "elapsed_ms": elapsed,
        "usage": response.get("usage", {}),
        "resolved_model": response.get("model", model),
        "provider": provider,
    }


def run_model(name: str, cases: list[dict], batch_size: int, workers: int, keys: dict, models: dict) -> dict:
    work = batches(cases, batch_size)
    started = time.perf_counter()
    outputs: dict[int, dict] = {}

    def run(index_and_batch: tuple[int, list[dict]]) -> tuple[int, dict]:
        index, batch = index_and_batch
        if name == "jev":
            return index, jev_batch(batch, keys["openrouter"])
        return index, chat_batch(batch, provider=name, model=models[name], key=keys[name])

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run, item): item[0] for item in enumerate(work)}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            outputs[index] = future.result()[1]
            done += 1
            if done % 10 == 0 or done == len(work):
                print(f"[{name}] {done}/{len(work)} batches", flush=True)

    predictions = {}
    latencies = []
    usages = []
    resolved_models = Counter()
    providers = Counter()
    for index in sorted(outputs):
        output = outputs[index]
        predictions.update(output["predictions"])
        latencies.append(float(output["elapsed_ms"]))
        usages.append(output.get("usage") or {})
        if output.get("resolved_model"):
            resolved_models[str(output["resolved_model"])] += 1
        if output.get("provider"):
            providers[str(output["provider"])] += 1

    return {
        "predictions": predictions,
        "batch_latencies_ms": latencies,
        "usage_records": usages,
        "wall_time_s": time.perf_counter() - started,
        "resolved_models": dict(resolved_models),
        "providers": dict(providers),
    }


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)]


def score_model(name: str, cases: list[dict], run: dict, batch_size: int) -> dict:
    confusion = {truth: {pred: 0 for pred in CATEGORIES + ["INVALID"]} for truth in CATEGORIES}
    rows = []
    confidences = []
    correct = 0
    for case in cases:
        value = run["predictions"].get(case["id"], {})
        prediction = value.get("prediction") or "INVALID"
        if prediction not in CATEGORIES:
            prediction = "INVALID"
        is_correct = prediction == case["truth"]
        correct += int(is_correct)
        confusion[case["truth"]][prediction] += 1
        confidence = value.get("confidence")
        if isinstance(confidence, (int, float)):
            confidences.append(float(confidence))
        rows.append({
            "email_id": case["id"],
            "expected": case["truth"],
            "predicted": prediction,
            "correct": is_correct,
            "confidence": confidence,
            "probabilities": value.get("probabilities"),
        })

    per_category = {}
    f1_values = []
    for category in CATEGORIES:
        tp = confusion[category][category]
        fp = sum(confusion[truth][category] for truth in CATEGORIES if truth != category)
        fn = sum(confusion[category][pred] for pred in confusion[category] if pred != category)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_category[category] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": sum(confusion[category].values()),
        }

    usage = {
        "input_tokens": sum(int(item.get("input_tokens", item.get("prompt_tokens", 0)) or 0) for item in run["usage_records"]),
        "output_tokens": sum(int(item.get("output_tokens", item.get("completion_tokens", 0)) or 0) for item in run["usage_records"]),
        "cost_usd": sum(float(item.get("cost", 0) or 0) for item in run["usage_records"]),
    }
    latencies = run["batch_latencies_ms"]
    confidence_routing = []
    for threshold in [0.6, 0.7, 0.8, 0.9]:
        eligible = [
            row for row in rows
            if isinstance(row.get("confidence"), (int, float)) and row["confidence"] >= threshold
        ]
        eligible_errors = sum(not row["correct"] for row in eligible)
        confidence_routing.append({
            "threshold": threshold,
            "auto_cases": len(eligible),
            "coverage": len(eligible) / len(rows),
            "auto_errors": eligible_errors,
            "auto_accuracy": ((len(eligible) - eligible_errors) / len(eligible)) if eligible else None,
            "fallback_cases": len(rows) - len(eligible),
        })
    return {
        "name": name,
        "accuracy": correct / len(cases),
        "correct": correct,
        "total": len(cases),
        "macro_f1": statistics.mean(f1_values),
        "per_category": per_category,
        "confusion_matrix": confusion,
        "latency": {
            "batch_size": batch_size,
            "median_batch_ms": statistics.median(latencies),
            "p95_batch_ms": percentile(latencies, 0.95),
            "effective_ms_per_email": run["wall_time_s"] * 1000 / len(cases),
            "wall_time_s": run["wall_time_s"],
        },
        "usage": usage,
        "mean_reported_confidence": statistics.mean(confidences) if confidences else None,
        "confidence_routing": confidence_routing,
        "resolved_models": run["resolved_models"],
        "providers": run["providers"],
        "predictions": rows,
    }


def summary_markdown(result: dict) -> str:
    lines = [
        "# Decision Model Benchmark",
        "",
        f"Generated: {result['generated_at']}",
        "",
        f"Dataset: {result['dataset']['cases']} labelled shipping emails. Shared task: five-class email routing.",
        "",
        "| Model | Accuracy | Macro F1 | Median batch | Effective time/email | Input tokens | Output tokens | Reported cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in [k for k in ["jev", "gemini"] if k in result["models"]]:
        model = result["models"][key]
        usage = model["usage"]
        cost = f"${usage['cost_usd']:.6f}" if usage["cost_usd"] else "Not returned"
        lines.append(
            f"| {key.title()} | {model['accuracy']:.2%} | {model['macro_f1']:.4f} | "
            f"{model['latency']['median_batch_ms']:.0f} ms | {model['latency']['effective_ms_per_email']:.1f} ms | "
            f"{usage['input_tokens']:,} | {usage['output_tokens']:,} | {cost} |"
        )
    lines += [
        "",
        "## Scope",
        "",
        "This is a routing benchmark because classification is the capability shared by both models. "
        "It does not compare OCR, image understanding, field extraction, or reply generation; Jev does not generate open-ended text.",
        "",
        "The models received the same subject, sender, email body (capped at 3,000 characters), and attachment file names. "
        "Attachment contents were not sent. Calls used batches and deterministic settings where supported.",
        "",
        "Reported confidence is stored for inspection but should not be compared as if it were the same measurement: "
        "Jev returns a probability-derived confidence, while Gemini self-reports confidence in generated JSON.",
        "",
        "## Jev confidence routing",
        "",
        "| Threshold | Auto coverage | Accuracy of auto cases | Fallback cases |",
        "|---:|---:|---:|---:|",
    ]
    for route in result["models"]["jev"]["confidence_routing"]:
        lines.append(
            f"| {route['threshold']:.2f} | {route['coverage']:.2%} | "
            f"{route['auto_accuracy']:.2%} | {route['fallback_cases']} |"
        )
    lines.append("")
    for key in [k for k in ["jev", "gemini"] if k in result["models"]]:
        model = result["models"][key]
        lines += [f"## {key.title()} category results", "", "| Category | Precision | Recall | F1 | Support |", "|---|---:|---:|---:|---:|"]
        for category in CATEGORIES:
            metric = model["per_category"][category]
            lines.append(
                f"| {category} | {metric['precision']:.2%} | {metric['recall']:.2%} | "
                f"{metric['f1']:.4f} | {metric['support']} |"
            )
        lines.append("")
    return "\n".join(lines)


def run_decision_benchmark(
    limit: int | None = None,
    batch_size: int = 8,
    workers: int = 4,
    on_progress: callable | None = None,
) -> dict:
    load_env()

    keys = {
        "openrouter": os.environ.get("OPENROUTER_API_KEY", ""),
        "gemini": os.environ.get("GEMINI_API_KEY", ""),
    }
    if not keys["openrouter"] or not keys["gemini"]:
        raise ValueError("OPENROUTER_API_KEY and GEMINI_API_KEY are required in backend/.env")
    models = {
        "jev": "typesafe/jev-1.13",
        "gemini": os.environ.get("MODEL", "gemini-3.1-flash-lite"),
    }
    cases = load_cases(limit)
    print(f"Loaded {len(cases)} labelled cases", flush=True)

    model_names = ["jev", "gemini"]
    scored = {}
    for idx, name in enumerate(model_names):
        if on_progress:
            on_progress({
                "status": "running",
                "current_model": name,
                "model_label": models[name],
                "model_index": idx,
                "total_models": len(model_names),
                "pct": int((idx / len(model_names)) * 100),
                "total_cases": len(cases),
            })
        print(f"Starting {name}: {models[name]}", flush=True)
        run = run_model(name, cases, batch_size, workers, keys, models)
        scored[name] = score_model(name, cases, run, batch_size)
        print(
            f"Finished {name}: accuracy={scored[name]['accuracy']:.2%}, "
            f"macro_f1={scored[name]['macro_f1']:.4f}",
            flush=True,
        )

    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    result = {
        "schema_version": 1,
        "generated_at": generated_at,
        "dataset": {
            "name": "SDOC Clearview labelled inbox",
            "cases": len(cases),
            "category_distribution": dict(Counter(case["truth"] for case in cases)),
            "input": "subject, sender, first 3000 body characters, attachment file names",
            "attachment_contents_sent": False,
        },
        "methodology": {
            "task": "five-class shipping email routing",
            "categories": CATEGORIES,
            "batch_size": batch_size,
            "workers": workers,
            "temperature": 0,
            "confidence_note": "Jev confidence and chat-model self-reported confidence are not directly comparable.",
        },
        "requested_models": models,
        "models": scored,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = RESULTS_DIR / f"decision-models-{stamp}.json"
    md_path = RESULTS_DIR / f"decision-models-{stamp}.md"
    json_text = json.dumps(result, indent=2, ensure_ascii=False)
    md_text = summary_markdown(result)
    compact_result = {
        **{key: value for key, value in result.items() if key != "models"},
        "models": {
            key: {metric: value for metric, value in model.items() if metric != "predictions"}
            for key, model in result["models"].items()
        },
        "highlights": {
            "highest_accuracy": max(scored, key=lambda key: scored[key]["accuracy"]),
            "highest_macro_f1": max(scored, key=lambda key: scored[key]["macro_f1"]),
            "lowest_effective_latency": min(
                scored, key=lambda key: scored[key]["latency"]["effective_ms_per_email"]
            ),
            "lowest_reported_cost": min(
                (key for key in scored if scored[key]["usage"]["cost_usd"] > 0),
                key=lambda key: scored[key]["usage"]["cost_usd"],
            ),
        },
    }
    compact_text = json.dumps(compact_result, indent=2, ensure_ascii=False)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    (RESULTS_DIR / f"decision-models-{stamp}-summary.json").write_text(compact_text, encoding="utf-8")
    (RESULTS_DIR / "latest.json").write_text(json_text, encoding="utf-8")
    (RESULTS_DIR / "latest.md").write_text(md_text, encoding="utf-8")
    (RESULTS_DIR / "latest-summary.json").write_text(compact_text, encoding="utf-8")
    print(f"Saved {json_path}", flush=True)
    print(f"Saved {md_path}", flush=True)

    if on_progress:
        on_progress({
            "status": "completed",
            "current_model": None,
            "model_label": None,
            "model_index": 3,
            "total_models": 3,
            "pct": 100,
            "total_cases": len(cases),
            "stamp": stamp,
            "generated_at": generated_at,
        })

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    run_decision_benchmark(args.limit, args.batch_size, args.workers)


if __name__ == "__main__":
    main()
