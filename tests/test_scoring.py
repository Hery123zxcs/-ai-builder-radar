from schemas import DimensionScore, GrowthMetrics
from scoring import calculate_scorecard, normalized_available_score


def test_missing_dimension_is_not_treated_as_zero():
    dimensions = [
        DimensionScore(
            dimension_name="available",
            raw_score=80,
            weight=50,
            weighted_score=40,
            available=True,
            source_type="github_metric",
            explanation="known",
            confidence=1,
        ),
        DimensionScore(
            dimension_name="missing",
            weight=50,
            available=False,
            source_type="readme_analysis",
            explanation="数据不足",
            confidence=0,
        ),
    ]
    assert normalized_available_score(dimensions) == 80


def test_coverage_uses_available_weights(complete_bundle):
    score = calculate_scorecard(complete_bundle, GrowthMetrics(), semantic=None)
    assert score.data_coverage == 0.6
    assert score.project_potential_score is not None
    assert score.builder_execution_score is not None
    assert score.ecosystem_fit_score is None
    assert "No historical data" in score.risk_tags
    assert "LLM evidence insufficient" in score.risk_tags


def test_archived_and_missing_license_risks_are_objective(complete_bundle):
    bundle = complete_bundle.model_copy(deep=True)
    bundle.repository.archived = True
    bundle.repository.license = None
    score = calculate_scorecard(bundle)
    assert "Archived repository" in score.risk_tags
    assert "No license" in score.risk_tags
    assert "Commercial use unclear" in score.risk_tags
    execution = next(
        item for item in score.dimensions if item.dimension_name.startswith("D.")
    )
    assert execution.raw_score == 0
