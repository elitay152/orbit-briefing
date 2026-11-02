import argparse
from datetime import datetime, timezone
import logging
import re
import time

from ollama import chat
import pandas as pd

import orbit.agent.agent as agent
from orbit.agent.eval_cases import EVAL_SETS
from orbit.config import setup_logging, ANALYSIS_DIR, OLLAMA_MODEL, TS_FORMAT

logger = logging.getLogger(__name__)

# constants
STOPPED_PREFIX = "Stopped:"   # ask() gave up without answering
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")

def extract_numbers(answer: str) -> list[float]:
    """Return every number in the answer; '11,133' counts as 11133."""
    return [float(n) for n in NUMBER_PATTERN.findall(answer.replace(",", ""))]

def score_answer(case: dict, answer: str, gold_values: list) -> bool:
    """Return True if the answer is correct for this case.

    The checks are deliberately simple: a number case passes if the right number
    appears anywhere in the answer, even if the sentence around it is wrong.
    """
    if answer.startswith(STOPPED_PREFIX):
        return False

    if case["kind"] == "number":
        numbers = extract_numbers(answer)
        return any(abs(n - float(g)) <= case["tolerance"] for n in numbers for g in gold_values)

    if case["kind"] == "text":
        return any(str(g).lower() in answer.lower() for g in gold_values)

    if case["kind"] == "decline":
        return not any(ch.isdigit() for ch in answer)

    raise ValueError(f"Unknown case kind: {case['kind']}")

def gold_values(con, case: dict) -> list:
    """Run the case's gold query; every value in the first column is an accepted answer."""
    if "gold_sql" not in case:
        return []
    return [row[0] for row in con.execute(case["gold_sql"]).fetchall()]

def run_case(con, case: dict) -> dict:
    """Ask one question and score the result; an error counts as a failed case."""
    gold = gold_values(con, case)
    start = time.perf_counter()
    try:
        answer = agent.ask(case["question"])
        correct = score_answer(case, answer, gold)
    except Exception as e:             # one bad case shouldn't lose the whole run
        logger.exception("%s: error", case["id"])
        answer = f"ERROR: {e}"
        correct = False

    return {
        "id": case["id"],
        "kind": case["kind"],
        "correct": correct,
        "seconds": round(time.perf_counter() - start, 1),
        "question": case["question"],
        "gold": gold,
        "answer": answer,
    }

def summarize(results: pd.DataFrame) -> str:
    """Overall score, score per kind, and the failed cases."""
    lines = [
        f"Score: {results['correct'].sum()} / {len(results)} correct "
        f"({results['correct'].mean():.0%}), "
        f"average {results['seconds'].mean():.1f}s per question",
        "",
        results.groupby("kind")["correct"].agg(["sum", "count"]).to_string(),
    ]

    failed = results[~results["correct"]]
    if not failed.empty:
        lines += ["", "Failed:"]
        for row in failed.itertuples():
            lines.append(f"- {row.id}: expected {row.gold}, got: {row.answer}")

    return "\n".join(lines)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score the agent on a set of questions.")
    parser.add_argument("--set", choices=EVAL_SETS, default="tuning", dest="case_set",
                        help="tuning: used to improve the agent; heldout: never used for tuning")
    args = parser.parse_args()
    cases = EVAL_SETS[args.case_set]

    setup_logging()
    agent._con = agent.open_sandbox()

    logger.info("Warming up %s...", OLLAMA_MODEL)
    chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": "Reply OK"}], keep_alive="30m")

    rows = []
    for number, case in enumerate(cases, start=1):
        row = run_case(agent._con, case)
        logger.info("[%d/%d] %s: %s (%.1fs)", number, len(cases), case["id"],
                    "PASS" if row["correct"] else "FAIL", row["seconds"])
        rows.append(row)

    results = pd.DataFrame(rows)
    print("\n" + summarize(results))

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime(TS_FORMAT)
    model_name = OLLAMA_MODEL.replace(":", "-")   # colons aren't allowed in Windows file names
    path = ANALYSIS_DIR / f"eval_{args.case_set}_{model_name}_{timestamp}.csv"
    results.to_csv(path, index=False)
    logger.info("Results saved to %s", path)
