from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ALLOWED_LABELS = {"safe", "attack"}
ALLOWED_LANGUAGES = {"tr", "en", "tr-en"}
ALLOWED_SPLITS = {"unassigned", "train", "validation", "locked_test"}
REQUIRED = {
    "id", "text", "label", "language", "category", "attack_family",
    "difficulty", "obfuscation", "source", "source_id", "license",
    "pair_id", "split",
}

def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON at line {lineno}: {exc}")
            rows.append(row)
    return rows

def normalize(text: str) -> str:
    return " ".join(text.lower().split())

def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/master.jsonl")
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    rows = load_jsonl(path)
    errors = []
    ids = set()
    normalized = defaultdict(list)
    pair_splits = defaultdict(set)

    for idx, row in enumerate(rows, 1):
        missing = REQUIRED - row.keys()
        if missing:
            errors.append(f"row {idx}: missing fields {sorted(missing)}")
            continue

        if row["id"] in ids:
            errors.append(f"row {idx}: duplicate id {row['id']}")
        ids.add(row["id"])

        if row["label"] not in ALLOWED_LABELS:
            errors.append(f"row {idx}: invalid label {row['label']}")
        if row["language"] not in ALLOWED_LANGUAGES:
            errors.append(f"row {idx}: invalid language {row['language']}")
        if row["split"] not in ALLOWED_SPLITS:
            errors.append(f"row {idx}: invalid split {row['split']}")

        if row["label"] == "safe" and row["attack_family"] != "none":
            errors.append(f"row {idx}: safe row must use attack_family=none")
        if row["label"] == "attack" and row["attack_family"] == "none":
            errors.append(f"row {idx}: attack row must have an attack_family")

        key = normalize(row["text"])
        normalized[key].append(row["id"])

        if row["pair_id"]:
            pair_splits[row["pair_id"]].add(row["split"])

    for text, row_ids in normalized.items():
        if len(row_ids) > 1:
            errors.append(f"exact duplicate text: {row_ids}")

    for pair_id, splits in pair_splits.items():
        real_splits = {s for s in splits if s != "unassigned"}
        if len(real_splits) > 1:
            errors.append(
                f"pair_id {pair_id} leaks across splits: {sorted(real_splits)}"
            )

    labels = Counter(row["label"] for row in rows)
    langs = Counter(row["language"] for row in rows)
    splits = Counter(row["split"] for row in rows)
    families = Counter(
        row["attack_family"] for row in rows if row["label"] == "attack"
    )
    categories = Counter(row["category"] for row in rows if row["label"] == "safe")

    print(f"Rows: {len(rows)}")
    print(f"Labels: {dict(labels)}")
    print(f"Languages: {dict(langs)}")
    print(f"Splits: {dict(splits)}")
    print(f"Attack families: {dict(families)}")
    print(f"Safe categories: {dict(categories)}")

    if errors:
        print(f"\\nFAILED: {len(errors)} issue(s)")
        for error in errors[:50]:
            print(f"- {error}")
        raise SystemExit(1)

    print("\nPASS: basic schema/leakage checks succeeded.")

if __name__ == "__main__":
    main()
