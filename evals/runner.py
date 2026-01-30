#!/usr/bin/env python3
"""Eval runner for wiresum classifier.

Evals are self-contained:
- Prompt template: ../wiresum/prompts/classification.j2
- Test config (interests, model): config.json
- Test cases: golden.jsonl

Usage:
    python evals/runner.py              # Run evals
    python evals/runner.py --verbose    # Show reasoning
"""

import json
import re
import sys
from pathlib import Path

from groq import Groq
from jinja2 import Environment, FileSystemLoader


PROMPT_DIR = Path(__file__).parent.parent / "wiresum" / "prompts"
PROMPT_FILE = "classification.j2"


def load_prompt_template():
    """Load the Jinja2 prompt template."""
    env = Environment(loader=FileSystemLoader(PROMPT_DIR))
    return env.get_template(PROMPT_FILE)


def load_config(path: Path = None) -> dict:
    """Load eval config (interests + model)."""
    if path is None:
        path = Path(__file__).parent / "config.json"
    with open(path) as f:
        return json.load(f)


def load_golden(path: Path = None) -> list[dict]:
    """Load golden eval set from JSONL."""
    if path is None:
        path = Path(__file__).parent / "golden.jsonl"
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def format_entry(item: dict) -> str:
    """Format entry for classification."""
    parts = []
    if item.get("feed_name"):
        parts.append(f"Feed: {item['feed_name']}")
    if item.get("title"):
        parts.append(f"Title: {item['title']}")
    if item.get("url"):
        parts.append(f"URL: {item['url']}")
    if item.get("author"):
        parts.append(f"Author: {item['author']}")
    if item.get("content"):
        content = item["content"][:3000] if len(item["content"]) > 3000 else item["content"]
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()
        parts.append(f"Content: {content}")
    return "\n".join(parts)


def classify(client: Groq, model: str, system_prompt: str, entry_text: str) -> tuple[str | None, bool, str]:
    """Classify an entry and return (interest, is_signal, reasoning)."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": entry_text},
        ],
        temperature=0.1,
        max_tokens=500,
    )

    content = response.choices[0].message.content

    try:
        if "```" in content:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if match:
                content = match.group(1)

        data = json.loads(content)
        interest = data.get("interest")
        if interest == "null" or interest == "":
            interest = None
        is_signal = bool(data.get("is_signal", False))
        reasoning = data.get("reasoning", "No reasoning")
        return (interest, is_signal, reasoning)
    except (json.JSONDecodeError, KeyError) as e:
        return (None, False, f"Parse error: {e}")


def run_evals(verbose: bool = False) -> dict:
    """Run classifier against golden set."""
    import os
    from dotenv import load_dotenv
    load_dotenv()

    # Load prompt template and config
    template = load_prompt_template()
    config = load_config()
    golden = load_golden()

    # Render system prompt with interests
    system_prompt = template.render(interests=config["interests"])

    # Initialize Groq client
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    model = config["model"]

    results = []
    correct = 0

    print(f"\nRunning {len(golden)} evals (model: {model})...\n")
    print("-" * 80)

    for item in golden:
        entry_text = format_entry(item)
        interest, is_signal, reasoning = classify(client, model, system_prompt, entry_text)

        actual = interest if is_signal else "filtered"
        expected = item["expected"]

        is_correct = actual == expected
        if is_correct:
            correct += 1
            status = "\033[92mPASS\033[0m"
        else:
            status = "\033[91mFAIL\033[0m"

        results.append({
            "title": item["title"][:50],
            "expected": expected,
            "actual": actual,
            "correct": is_correct,
            "reasoning": reasoning,
        })

        title_short = item["title"][:40] + "..." if len(item["title"]) > 40 else item["title"]
        print(f"  [{status}] {title_short}")
        print(f"         Expected: {expected:12} | Actual: {actual}")
        if verbose:
            reason_short = reasoning[:70] + "..." if len(reasoning) > 70 else reasoning
            print(f"         Reasoning: {reason_short}")
        print()

    print("-" * 80)

    accuracy = correct / len(golden) if golden else 0
    print(f"\nAccuracy: {correct}/{len(golden)} ({accuracy:.0%})")

    failures = [r for r in results if not r["correct"]]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures:
            print(f"  - {f['title']}: expected {f['expected']}, got {f['actual']}")

    return {"accuracy": accuracy, "correct": correct, "total": len(golden), "results": results}


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    run_evals(verbose=verbose)
