from __future__ import annotations
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

EXPECTED = {
    "train": {
        "rows": 840,
        "labels": {"attack": 420, "safe": 420},
        "languages": {"tr": 378, "en": 378, "tr-en": 84},
    },
    "validation": {
        "rows": 180,
        "labels": {"attack": 90, "safe": 90},
        "languages": {"tr": 81, "en": 81, "tr-en": 18},
    },
    "locked_test": {
        "rows": 180,
        "labels": {"attack": 90, "safe": 90},
        "languages": {"tr": 81, "en": 81, "tr-en": 18},
    },
}

def load(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/master_v1_split.jsonl"
    rows = load(path)
    errors = []

    print(f"Rows: {len(rows)}")

    for split in ["train", "validation", "locked_test"]:
        subset = [r for r in rows if r["split"] == split]
        labels = dict(Counter(r["label"] for r in subset))
        languages = dict(Counter(r["language"] for r in subset))
        families = dict(Counter(
            r["attack_family"] for r in subset if r["label"] == "attack"
        ))
        safe_categories = dict(Counter(
            r["category"] for r in subset if r["label"] == "safe"
        ))

        print(f"\n[{split}]")
        print("Rows:", len(subset))
        print("Labels:", labels)
        print("Languages:", languages)
        print("Attack families:", families)
        print("Safe categories:", safe_categories)

        if len(subset) != EXPECTED[split]["rows"]:
            errors.append(f"{split}: wrong row count")
        if labels != EXPECTED[split]["labels"]:
            errors.append(f"{split}: wrong label distribution")
        if languages != EXPECTED[split]["languages"]:
            errors.append(f"{split}: wrong language distribution")

    pair_splits = defaultdict(set)
    for r in rows:
        if r.get("pair_id"):
            pair_splits[r["pair_id"]].add(r["split"])

    pair_leaks = [p for p, splits in pair_splits.items() if len(splits) > 1]
    print(f"\nPair-ID cross-split leaks: {len(pair_leaks)}")
    if pair_leaks:
        errors.append("pair_id leakage detected")

    texts = [r["text"] for r in rows]
    vec = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3,5),
        lowercase=True,
    )
    X = vec.fit_transform(texts)
    S = cosine_similarity(X)

    near_total = 0
    near_leaks = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            sim = float(S[i, j])
            if sim >= 0.85:
                near_total += 1
                if rows[i]["split"] != rows[j]["split"]:
                    near_leaks.append((rows[i]["id"], rows[j]["id"], sim))

    print(f"Near-duplicate pairs >= 0.85: {near_total}")
    print(f"Near-duplicate cross-split leaks: {len(near_leaks)}")
    if near_leaks:
        errors.append("near-duplicate leakage detected")

    if errors:
        print("\nFAIL")
        for error in errors:
            print(" -", error)
        raise SystemExit(1)

    print("\nPASS: exact split distributions and leakage constraints succeeded.")

if __name__ == "__main__":
    main()
