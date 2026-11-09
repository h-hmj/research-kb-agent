"""可独立测试的评测指标计算。"""

from __future__ import annotations

from typing import Any

from ..schemas.qa import QACitation
from ..schemas.retrieval import RetrievalResult
from .schemas import CaseResult, ExpectedSource


def source_matches(
    *,
    original_filename: str,
    page_number: int,
    document_id: str,
    expected: ExpectedSource,
) -> bool:
    """引用/检索结果与人工期望来源的匹配规则。"""
    if original_filename != expected.original_filename:
        return False
    if page_number != expected.page_number:
        return False
    if expected.document_id and document_id != expected.document_id:
        return False
    return True


def first_relevant_rank(
    results: list[RetrievalResult],
    expected_sources: list[ExpectedSource],
) -> int | None:
    for rank, result in enumerate(results, start=1):
        if any(
            source_matches(
                original_filename=result.original_filename,
                page_number=result.page_number,
                document_id=result.document_id,
                expected=source,
            )
            for source in expected_sources
        ):
            return rank
    return None


def citation_counts(
    citations: list[QACitation],
    expected_sources: list[ExpectedSource],
) -> tuple[int, int, int]:
    """返回 (正确 citation 数, 总 citation 数, 命中的期望来源数)。"""
    correct = 0
    matched_sources: set[int] = set()
    for citation in citations:
        matched = False
        for index, expected in enumerate(expected_sources):
            if source_matches(
                original_filename=citation.original_filename,
                page_number=citation.page_number,
                document_id=citation.document_id,
                expected=expected,
            ):
                matched = True
                matched_sources.add(index)
        if matched:
            correct += 1
    return correct, len(citations), len(matched_sources)


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator), 6)


def calculate_metrics(
    case_results: list[CaseResult],
    mode: str,
) -> dict[str, Any]:
    """计算单组（QA 或 Agent）指标。"""
    answerable = [
        result for result in case_results if result.expected_answerable
    ]
    unanswerable = [
        result for result in case_results if not result.expected_answerable
    ]

    retrieval_hits = sum(
        1 for result in answerable if result.retrieval_hit is True
    )
    reciprocal_rank = sum(
        (1.0 / result.first_relevant_rank)
        if result.first_relevant_rank
        else 0.0
        for result in answerable
    )
    retrieval = {
        "recall_at_k": _ratio(retrieval_hits, len(answerable)),
        "mrr_at_k": (
            round(reciprocal_rank / len(answerable), 6)
            if answerable
            else None
        ),
    }

    if mode == "retrieval":
        citation = {"precision": None, "recall": None}
        refusal = {
            "accuracy": None,
            "hallucinated_answer_rate": None,
            "false_refusal_rate": None,
        }
        answer = {"keyword_hit_rate": None, "keyword_evaluated_cases": 0}
        agent = {"rewrite_rate": None, "retry_success_rate": None}
        return {
            "retrieval": retrieval,
            "citation": citation,
            "refusal": refusal,
            "answer": answer,
            "agent": agent,
        }

    answered = [
        result for result in case_results if result.actual_status == "answered"
    ]
    citation_correct = sum(result.citation_correct_count for result in answered)
    citation_total = sum(result.citation_total_count for result in answered)
    expected_source_total = sum(
        result.expected_source_count for result in answerable
    )
    matched_source_total = sum(
        result.matched_expected_source_count for result in answerable
    )
    citation = {
        "precision": _ratio(citation_correct, citation_total),
        "recall": _ratio(matched_source_total, expected_source_total),
    }

    correct_refusals = 0
    for result in case_results:
        if result.expected_answerable and result.actual_status == "answered":
            correct_refusals += 1
        elif (
            not result.expected_answerable
            and result.actual_status == "refused"
        ):
            correct_refusals += 1
    hallucinated = sum(
        1
        for result in unanswerable
        if result.actual_status == "answered"
    )
    false_refusals = sum(
        1 for result in answerable if result.actual_status == "refused"
    )
    refusal = {
        "accuracy": _ratio(correct_refusals, len(case_results)),
        "hallucinated_answer_rate": _ratio(
            hallucinated,
            len(unanswerable),
        ),
        "false_refusal_rate": _ratio(false_refusals, len(answerable)),
    }

    keyword_results = [
        result
        for result in answerable
        if result.actual_status == "answered"
        and result.keyword_hit is not None
    ]
    keyword_hits = sum(
        1 for result in keyword_results if result.keyword_hit is True
    )
    answer = {
        "keyword_hit_rate": _ratio(keyword_hits, len(keyword_results)),
        "keyword_evaluated_cases": len(keyword_results),
    }

    if mode == "agent":
        rewrites = [result for result in case_results if result.rewrite_attempted]
        retry_successes = sum(
            1 for result in rewrites if result.retry_success is True
        )
        agent = {
            "rewrite_rate": _ratio(len(rewrites), len(case_results)),
            "retry_success_rate": _ratio(
                retry_successes,
                len(rewrites),
            ),
        }
    else:
        agent = {"rewrite_rate": None, "retry_success_rate": None}

    return {
        "retrieval": retrieval,
        "citation": citation,
        "refusal": refusal,
        "answer": answer,
        "agent": agent,
    }
