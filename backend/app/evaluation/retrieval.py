"""Retrieval recall benchmark (spec §13: target ≥90% recall on an annotated pilot benchmark).

A benchmark is JSON written by domain reviewers. Relevant evidence is identified by document
name and a quote, not by chunk IDs, so annotations survive re-processing:

    {
      "name": "pilot-v1",
      "top_k": 10,
      "target_recall": 0.9,
      "cases": [
        {
          "id": "jane-mentoring",
          "category": "board-leadership",          # award category code
          "candidate": "Jane Doe",                 # or "finalist_category_id": "<uuid>"
          "criterion": "mentoring",                # rubric criterion code, or "query": "..."
          "relevant": [{"document": "nomination.pdf", "quote": "mentors twelve women"}]
        }
      ]
    }

Usage: python -m app.evaluation.retrieval BENCHMARK.json [--top-k N] [--output REPORT.json]
Exits with status 1 when recall is below the target, so it can gate CI or a release.
"""

import argparse
import json
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.citations import normalise
from app.services.retrieval import Retriever, criterion_query


class BenchmarkError(ValueError):
    pass


@dataclass
class CaseResult:
    id: str
    query: str
    relevant: int
    found: int
    recall: float
    reciprocal_rank: float
    ranks: list[int | None]
    flags: list[str] = field(default_factory=list)


@dataclass
class Report:
    name: str
    top_k: int
    target_recall: float
    cases: list[CaseResult]
    recall: float  # micro-averaged over all relevant items
    mean_case_recall: float
    mrr: float
    passed: bool
    config: dict

    def summary(self) -> str:
        lines = [
            f"Benchmark {self.name}: recall@{self.top_k} = {self.recall:.1%} "
            f"(target {self.target_recall:.0%}) — {'PASS' if self.passed else 'FAIL'}",
            f"  mean case recall {self.mean_case_recall:.1%}, MRR {self.mrr:.3f}",
        ]
        for case in self.cases:
            marker = "ok " if case.found == case.relevant else "MISS"
            lines.append(
                f"  [{marker}] {case.id}: {case.found}/{case.relevant} "
                f"ranks={case.ranks} flags={case.flags}"
            )
        return "\n".join(lines)


def _resolve_candidate(session: Session, case: dict) -> tuple[uuid.UUID, uuid.UUID]:
    if "finalist_category_id" in case:
        row = session.execute(
            text("SELECT id, category_id FROM finalist_categories WHERE id = :id"),
            {"id": uuid.UUID(case["finalist_category_id"])},
        ).one_or_none()
        if row is None:
            raise BenchmarkError(f"{case['id']}: unknown finalist_category_id")
        return row.id, row.category_id
    rows = session.execute(
        text(
            "SELECT fc.id, fc.category_id FROM finalist_categories fc "
            "JOIN finalists f ON f.id = fc.finalist_id "
            "JOIN award_categories c ON c.id = fc.category_id "
            "WHERE c.code = :code AND lower(f.full_name) = lower(:name)"
        ),
        {"code": case["category"], "name": case["candidate"]},
    ).all()
    if len(rows) != 1:
        found = "no" if not rows else "several"
        raise BenchmarkError(
            f"{case['id']}: {found} candidates named {case['candidate']!r} in "
            f"{case['category']!r}; use finalist_category_id"
        )
    return rows[0].id, rows[0].category_id


def _query(session: Session, case: dict, category_id: uuid.UUID) -> str:
    if ("query" in case) == ("criterion" in case):
        raise BenchmarkError(f"{case['id']}: give exactly one of query or criterion")
    if "query" in case:
        return case["query"]
    row = session.execute(
        text(
            "SELECT rc.name, rc.description, rc.evidence_expectations FROM rubric_criteria rc "
            "JOIN rubric_versions rv ON rv.id = rc.rubric_version_id "
            "WHERE rv.category_id = :category AND rc.code = :code "
            "ORDER BY rv.version DESC LIMIT 1"
        ),
        {"category": category_id, "code": case["criterion"]},
    ).one_or_none()
    if row is None:
        raise BenchmarkError(f"{case['id']}: unknown criterion {case['criterion']!r}")
    return criterion_query(row.name, row.description, row.evidence_expectations)


def run_benchmark(
    session: Session, retriever: Retriever, benchmark: dict, top_k: int | None = None
) -> Report:
    top_k = top_k or benchmark.get("top_k") or retriever.settings.retrieval_top_k
    results: list[CaseResult] = []
    config: dict = {}
    for case in benchmark["cases"]:
        if not case.get("relevant"):
            raise BenchmarkError(f"{case.get('id')}: needs at least one relevant item")
        fc_id, category_id = _resolve_candidate(session, case)
        query = _query(session, case, category_id)
        retrieved = retriever.search(session, fc_id, query, top_k=top_k)
        config = retrieved.config

        ranks: list[int | None] = []
        for item in case["relevant"]:
            quote = normalise(item["quote"])
            rank = next(
                (
                    p.rank
                    for p in retrieved.passages
                    if quote in normalise(p.content)
                    and ("document" not in item or p.filename == item["document"])
                ),
                None,
            )
            ranks.append(rank)
        found = sum(r is not None for r in ranks)
        first = min((r for r in ranks if r is not None), default=None)
        results.append(
            CaseResult(
                id=case["id"],
                query=query,
                relevant=len(ranks),
                found=found,
                recall=found / len(ranks),
                reciprocal_rank=1 / first if first else 0.0,
                ranks=ranks,
                flags=retrieved.flags,
            )
        )

    total = sum(r.relevant for r in results)
    recall = sum(r.found for r in results) / total if total else 0.0
    target = float(benchmark.get("target_recall", 0.9))
    return Report(
        name=benchmark.get("name", "benchmark"),
        top_k=top_k,
        target_recall=target,
        cases=results,
        recall=recall,
        mean_case_recall=sum(r.recall for r in results) / len(results) if results else 0.0,
        mrr=sum(r.reciprocal_rank for r in results) / len(results) if results else 0.0,
        passed=recall >= target,
        config=config,
    )


def main() -> None:
    from app.config import get_settings
    from app.db import get_engine
    from app.services.retrieval import get_retriever

    parser = argparse.ArgumentParser(prog="python -m app.evaluation.retrieval")
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--output", type=Path, help="write the full report as JSON")
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text())
    retriever = get_retriever(get_settings())
    with Session(get_engine()) as session:
        report = run_benchmark(session, retriever, benchmark, args.top_k)
    print(report.summary())
    if args.output:
        args.output.write_text(json.dumps(asdict(report), indent=2))
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
