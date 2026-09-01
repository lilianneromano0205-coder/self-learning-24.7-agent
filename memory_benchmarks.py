"""Offline memory benchmark adapters. No downloads, paid judges or eval().

Source formats verified 2026-08-30. Public V2 deliberately omits answer-bearing
locations, so retrieval accuracy is unavailable without separately held labels.
Text retrieval is not multimodal QA nor a claim of the official headline score.
"""
import argparse
import copy
import hashlib
import json
import os
import time
from pathlib import Path

import retrieval

SPECS = {
    "longmemeval_v2": {"license": "Apache-2.0", "source": "https://huggingface.co/datasets/xiaowu0162/longmemeval-v2"},
    "longmemeval": {"license": "MIT", "source": "https://github.com/xiaowu0162/LongMemEval"},
    "memoryagentbench": {"license": "MIT", "source": "https://huggingface.co/datasets/ai-hyz/MemoryAgentBench"},
}
MAB_SPLITS = ("Accurate_Retrieval", "Test_Time_Learning", "Long_Range_Understanding", "Conflict_Resolution")


def _read(path):
    with open(path, encoding="utf-8") as f:
        if str(path).endswith(".jsonl"):
            return [json.loads(line) for line in f if line.strip()]
        return json.load(f)


def _record(key, text, source, **metadata):
    return dict(id=str(key), text=text, source_tier=4, provenance=source,
                observed_at=None, valid=True, retracted=False, superseded_by=None,
                kind="memory_files", **metadata)


def _case(key, question, category, records, answers, **extra):
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question text required")
    return dict(id=str(key), question=question, category=category, records=records,
                answers=answers if isinstance(answers, list) else [str(answers)], **extra)


def load(name, path, *, split=None, tier="small"):
    """Load owner-supplied local exports; retain a digest of every input file."""
    if name not in SPECS:
        raise ValueError("unknown memory benchmark")
    paths, cases = [], []
    if name == "longmemeval_v2":
        if tier not in ("small", "medium"):
            raise ValueError("V2 tier must be small or medium")
        paths = [Path(path, "questions.jsonl"), Path(path, "trajectories.jsonl"),
                 Path(path, "haystacks", f"lme_v2_{tier}.json")]
        questions, trajectories, haystacks = [_read(p) for p in paths]
        ids = [str(t["id"]) for t in trajectories]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate trajectory ids")
        indexed = {}
        for t in trajectories:
            # Answer annotations and evaluator specification never enter memory.
            text = json.dumps({k: t.get(k) for k in ("goal", "outcome", "start_url")}, ensure_ascii=False)
            for state in t.get("states", []):
                text += "\n" + json.dumps({k: state.get(k) for k in
                    ("state_index", "step", "url", "action", "accessibility_tree", "screenshot")}, ensure_ascii=False)
            indexed[str(t["id"])] = _record(t["id"], text, f"{SPECS[name]['source']}#trajectory-{t['id']}",
                                           domain=t.get("domain"), environment=t.get("environment"))
        for q in questions:
            history = haystacks.get(str(q["id"]))
            if not isinstance(history, list) or any(str(i) not in indexed for i in history):
                raise ValueError("missing or unresolved question haystack")
            cases.append(_case(q["id"], q["question"], q["question_type"],
                               [copy.deepcopy(indexed[str(i)]) for i in history], q["answer"],
                               relevant_ids=None, image=q.get("image"), eval_function=q.get("eval_function"),
                               retrieval_label_status="NOT_AVAILABLE_PUBLIC_RELEASE"))
    else:
        paths = [Path(path)]
        rows = _read(path)
        if not isinstance(rows, list):
            raise ValueError("benchmark export must be a JSON array or JSONL")
        if name == "longmemeval":
            for q in rows:
                ids, sessions, dates = q["haystack_session_ids"], q["haystack_sessions"], q["haystack_dates"]
                if len(ids) != len(sessions) or len(ids) != len(dates):
                    raise ValueError("mismatched LongMemEval history arrays")
                records = [_record(key, "\n".join(f"{m['role']}: {m['content']}" for m in session),
                                   f"{SPECS[name]['source']}#{key}", source_timestamp=date)
                           for key, session, date in zip(ids, sessions, dates)]
                relevant = q.get("answer_session_ids")
                if relevant is not None and not set(relevant) <= set(ids):
                    raise ValueError("unresolved evidence session")
                cases.append(_case(q["question_id"], q["question"], q["question_type"], records,
                                   q["answer"], relevant_ids=relevant, question_date=q.get("question_date")))
        else:
            if split not in MAB_SPLITS:
                raise ValueError("explicit official MemoryAgentBench split required")
            for index, row in enumerate(rows):
                questions, answers = row["questions"], row["answers"]
                if not isinstance(questions, list) or len(questions) != len(answers):
                    raise ValueError("mismatched MemoryAgentBench question/answer arrays")
                context = row["context"]
                if not isinstance(context, str):
                    raise ValueError("MemoryAgentBench context must be text")
                meta = row.get("metadata") or {}
                # Ordered fixed-size chunks implement incremental ingestion input;
                # this retrieval adapter does not claim to train a memory manager.
                words = context.split()
                records = [_record(f"{index}:{n // 512}", " ".join(words[n:n + 512]),
                                   f"{SPECS[name]['source']}#{split}/{index}", sequence=n // 512)
                           for n in range(0, len(words), 512)]
                for n, (question, answer) in enumerate(zip(questions, answers)):
                    if not isinstance(answer, list) or not all(isinstance(x, str) for x in answer):
                        raise ValueError("answer alternatives must be string lists")
                    cases.append(_case(f"{split}:{index}:{n}", question, split, copy.deepcopy(records), answer,
                                       relevant_ids=None, source_dataset=meta.get("source")))
    ids = [c["id"] for c in cases]
    if not cases or len(ids) != len(set(ids)):
        raise ValueError("non-empty distinct benchmark cases required")
    digests = {str(p.name if len(paths) == 1 else p.relative_to(path)):
               hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return dict(name=name, **SPECS[name], cases=cases, input_sha256=digests,
                fingerprint=hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest(),
                evidence_tier="external_local_export", split=split, tier=tier)


def compare(dataset, *, embedder=None, limit=5, reader=None, grader=None):
    """Matched immutable histories, four arms, task/category receipts and latency.

    Reader gets ONLY question/retrieved memory. The optional trusted independent
    grader gets expected data. Its results are custom mechanical QA, never the
    official provider-judge metric. Unknown labels stay null, not fabricated 0.
    """
    arms = {}
    for arm, mode in (("lexical", "lexical"), ("hybrid", "hybrid"),
                      ("no_memory", "no_memory"), ("simple_rag", "dense")):
        if mode == "dense" and embedder is None:
            arms[arm] = dict(status="NOT_RUN", reason="local embeddings unavailable", retrieval_accuracy=None)
            continue
        receipts, categories = [], {}
        for case in dataset["cases"]:
            start = time.perf_counter()
            hits = retrieval.rank(copy.deepcopy(case["records"]), case["question"], limit,
                                  mode=mode, embedder=embedder)
            relevant = case.get("relevant_ids")
            # Empty location labels (abstention) are not positive retrieval trials.
            score = (len(set(relevant) & {h["id"] for h in hits}) / len(set(relevant))) if relevant else None
            item = dict(case_id=case["id"], category=case["category"], retrieved_ids=[h["id"] for h in hits],
                        retrieval_accuracy=score, seconds=time.perf_counter() - start, answer_correct=None)
            if reader is not None and grader is not None and not case.get("image"):
                output = reader(case["question"], copy.deepcopy(hits))
                accepted = grader(copy.deepcopy(case), output)
                if type(accepted) is not bool:
                    raise ValueError("independent grader must return bool")
                item["answer_correct"] = accepted
            receipts.append(item)
            categories.setdefault(case["category"], []).append(item)
        def aggregate(items):
            scored = [r["retrieval_accuracy"] for r in items if r["retrieval_accuracy"] is not None]
            return dict(n=len(items), scored_n=len(scored),
                        retrieval_accuracy=sum(scored) / len(scored) if scored else None)
        qa = [r["answer_correct"] for r in receipts if r["answer_correct"] is not None]
        arms[arm] = dict(status="COMPLETE", **aggregate(receipts), receipts=receipts,
                         by_category={k: aggregate(v) for k, v in categories.items()},
                         seconds=sum(r["seconds"] for r in receipts),
                         answer_status="CUSTOM_MECHANICAL" if qa else "NOT_RUN",
                         answer_accuracy=sum(qa) / len(qa) if qa else None,
                         model_cost_usd=None, official_score=None)
    return dict(dataset=dataset["name"], fingerprint=dataset["fingerprint"], arms=arms,
                evidence_tier=dataset.get("evidence_tier", "unknown"),
                external_benchmark_result="NOT_RUN", official_score=None,
                limitations=["Retrieval-only unless a separate reader and grader are supplied",
                             "Text adapter does not evaluate screenshots", "No official judge was run"])


def run_external(name, path, **kwargs):
    try:
        dataset = load(name, path, **kwargs)
    except OSError:
        return dict(status="NOT_RUN", dataset=name, score=None, reason="local benchmark data unavailable")
    return compare(dataset)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=SPECS)
    parser.add_argument("path")
    parser.add_argument("--split")
    parser.add_argument("--tier", default="small", choices=("small", "medium"))
    args = parser.parse_args()
    print(json.dumps(run_external(args.dataset, args.path, split=args.split, tier=args.tier), indent=2))
