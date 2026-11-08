import pytest
from pydantic import ValidationError

from llm_analyzer import analyze_repository, validate_evidence
from schemas import EvidenceItem, ProjectSemanticAnalysis
from scoring import calculate_scorecard


def semantic(**updates):
    data = {
        "project_summary": "Evidence-grounded AI project discovery.",
        "problem_solved": None,
        "target_users": [],
        "categories": [],
        "technical_stack": [],
        "technical_differentiation": [],
        "problem_value": None,
        "product_maturity_explanation": None,
        "strengths": [],
        "risks": [],
        "ecosystem_fit": [],
        "collaboration_opportunities": [],
        "outreach_angle": None,
        "evidence": [
            {
                "claim": "Evidence-grounded AI project discovery.",
                "source": "description",
                "quote": "Evidence-grounded AI project discovery.",
            }
        ],
        "dimension_judgments": [],
        "confidence": 0.9,
    }
    data.update(updates)
    return ProjectSemanticAnalysis.model_validate(data)


def test_llm_schema_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        semantic(confidence=1.5)


def test_evidence_missing_removes_claim():
    analysis = semantic(
        evidence=[
            EvidenceItem(
                claim="Evidence-grounded AI project discovery.",
                source="description",
                quote="invented quote",
            )
        ]
    )
    cleaned, warnings = validate_evidence(
        analysis,
        {"description": "Evidence-grounded AI project discovery."},
        "radar",
    )
    assert cleaned.project_summary is None
    assert cleaned.evidence == []
    assert warnings


def test_exact_quote_keeps_supported_claim():
    analysis = semantic()
    cleaned, warnings = validate_evidence(
        analysis,
        {"description": "Evidence-grounded AI project discovery."},
        "radar",
    )
    assert cleaned.project_summary == analysis.project_summary
    assert len(cleaned.evidence) == 1
    assert not warnings


def test_llm_failure_still_allows_objective_scoring(complete_bundle):
    class FailingModel:
        def invoke(self, prompt):
            raise RuntimeError("provider unavailable")

    analysis, error = analyze_repository(complete_bundle, model=FailingModel())
    score = calculate_scorecard(complete_bundle, semantic=analysis)
    assert analysis is None
    assert "RuntimeError" in error
    assert score.overall_priority_score is not None
    assert score.ecosystem_fit_score is None
