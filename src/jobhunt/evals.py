"""Evals del auditor semántico de CVs.

Los casos (`evals/auditor/cases.jsonl`) son ficticios: un texto de CV, sus fuentes y la
etiqueta correcta, con la mutación sembrada anotada. El juez recibe los casos sin etiqueta;
después se puntúa contra las etiquetas.

La métrica principal es binaria: si el auditor deja pasar un texto infiel, el CV sale con
una afirmación falsa. Por eso importa más el recall de "no fiel" que la precisión por clase.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

LABELS = ("fiel", "exagera", "agrega")


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def blind(cases: list[dict]) -> list[dict]:
    return [{"id": c["id"], "sources": c["sources"], "cv_text": c["cv_text"]} for c in cases]


@dataclass
class Score:
    n: int
    accuracy_3: float
    unfaithful_recall: float     # de los textos infieles, cuántos marcó como no fieles
    false_alarm_rate: float      # de los fieles, cuántos marcó como no fieles
    confusion: dict[str, Counter]
    missed: list[str]            # infieles que dejó pasar
    false_alarms: list[str]
    missing_predictions: list[str]


def score(cases: list[dict], predictions: dict[str, str]) -> Score:
    confusion = {label: Counter() for label in LABELS}
    missed, alarms, missing = [], [], []
    correct = unfaithful = caught = faithful = flagged = 0
    for case in cases:
        gold, pred = case["label"], predictions.get(case["id"])
        if pred is None:
            missing.append(case["id"])
            pred = "fiel"  # sin respuesta cuenta como dejarlo pasar
        confusion[gold][pred] += 1
        correct += pred == gold
        if gold == "fiel":
            faithful += 1
            if pred != "fiel":
                flagged += 1
                alarms.append(case["id"])
        else:
            unfaithful += 1
            if pred != "fiel":
                caught += 1
            else:
                missed.append(case["id"])
    return Score(
        n=len(cases), accuracy_3=correct / len(cases),
        unfaithful_recall=caught / unfaithful if unfaithful else 1.0,
        false_alarm_rate=flagged / faithful if faithful else 0.0,
        confusion=confusion, missed=missed, false_alarms=alarms, missing_predictions=missing,
    )


def report(name: str, s: Score, cases: list[dict]) -> str:
    seeded = {c["id"]: c["seeded"] for c in cases}
    lines = [
        f"# Auditor eval — {name}", "",
        f"- Cases: {s.n}",
        f"- **Unfaithful caught (recall): {s.unfaithful_recall:.0%}**",
        f"- False alarms on faithful text: {s.false_alarm_rate:.0%}",
        f"- 3-class accuracy: {s.accuracy_3:.0%}", "",
        "| gold \\ predicted | " + " | ".join(LABELS) + " |",
        "|---|" + "---|" * len(LABELS),
    ]
    for gold in LABELS:
        lines.append(f"| {gold} | " + " | ".join(str(s.confusion[gold][p]) for p in LABELS) + " |")
    if s.missed:
        lines += ["", "Missed (unfaithful marked as faithful):"]
        lines += [f"- {i}: {seeded[i]}" for i in s.missed]
    if s.false_alarms:
        lines += ["", "False alarms:"] + [f"- {i}: {seeded[i]}" for i in s.false_alarms]
    if s.missing_predictions:
        lines += ["", f"No prediction: {', '.join(s.missing_predictions)}"]
    return "\n".join(lines) + "\n"
