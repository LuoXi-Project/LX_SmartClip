from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean


def _score_item(item: dict) -> dict:
    expected = int(item.get("expected_min_chapters", 3))
    tj = item.get("template_json") if isinstance(item.get("template_json"), dict) else {}
    structure = tj.get("structure") if isinstance(tj.get("structure"), list) else []
    chapters = tj.get("chapter_plan") if isinstance(tj.get("chapter_plan"), list) else []
    transitions = tj.get("transition_patterns") if isinstance(tj.get("transition_patterns"), list) else []
    guide = str(item.get("template_guide") or "")
    structure_ok = 1.0 if len(structure) >= 5 else 0.0
    chapter_ok = min(1.0, len(chapters) / max(1, expected))
    transition_ok = 1.0 if len(transitions) >= 2 else 0.5 if len(transitions) == 1 else 0.0
    reusable_ok = 1.0 if len(guide.strip()) >= 120 else 0.5 if len(guide.strip()) >= 40 else 0.0
    total = round((structure_ok + chapter_ok + transition_ok + reusable_ok) / 4, 3)
    return {
        "id": item.get("id") or "",
        "replica_type": item.get("replica_type") or "unknown",
        "structure_ok": structure_ok,
        "chapter_ok": round(chapter_ok, 3),
        "transition_ok": transition_ok,
        "reusable_ok": reusable_ok,
        "total": total,
    }


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        rows.append(json.loads(s))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Replica template quality evaluator")
    parser.add_argument("--input", required=True, help="jsonl file path")
    parser.add_argument("--output", default="", help="optional output json file")
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"input not found: {src}")

    rows = _load_jsonl(src)
    if not rows:
        raise SystemExit("empty dataset")

    scored = [_score_item(x) for x in rows]
    by_type: dict[str, list[float]] = {}
    for s in scored:
        by_type.setdefault(str(s["replica_type"]), []).append(float(s["total"]))

    summary = {
        "count": len(scored),
        "overall_mean": round(mean([float(x["total"]) for x in scored]), 3),
        "by_type_mean": {k: round(mean(v), 3) for k, v in by_type.items()},
        "failed_ids": [x["id"] for x in scored if float(x["total"]) < 0.7],
    }

    payload = {"summary": summary, "items": scored}
    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
