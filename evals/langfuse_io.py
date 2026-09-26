"""Gold set <-> Langfuse Dataset. Items are keyed by the gold id, so re-uploading updates in place."""
from typing import Any

DATASET = "ontario-injury-gold"


def upsert_dataset(lf: Any, gold: list[dict]) -> int:
    lf.create_dataset(name=DATASET, description="Ontario injury law gold set (evals/gold.jsonl)")
    for item in gold:
        lf.create_dataset_item(
            dataset_name=DATASET,
            input={"question": item["question"]},
            expected_output={"expected": item["expected"], "facts": item["facts"], "must_refuse": item["must_refuse"]},
            metadata={"topic": item["topic"]},
            id=item["id"],
        )
    return len(gold)
