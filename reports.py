"""CSV, JSON, and Markdown exports without fabricated claims."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from schemas import ManualReview, OutreachRecord, ProjectEvaluation


def ranking_csv(evaluations: list[ProjectEvaluation]) -> str:
    rows = []
    for rank, item in enumerate(_ranked(evaluations), start=1):
        repo, score = item.bundle.repository, item.scorecard
        rows.append(
            {
                "Rank": rank,
                "Project": repo.full_name,
                "Builder": repo.owner_login,
                "Stars": repo.stars,
                "Project Potential": score.project_potential_score,
                "Builder Execution": score.builder_execution_score,
                "Ecosystem Fit": score.ecosystem_fit_score,
                "Overall Priority": score.overall_priority_score,
                "Data Coverage": score.data_coverage,
                "Confidence": score.confidence,
                "Risk Tags": "; ".join(score.risk_tags),
            }
        )
    return _csv(rows)


def outreach_csv(records: list[OutreachRecord]) -> str:
    return _csv([record.model_dump(mode="json") for record in records])


def manual_reviews_csv(reviews: list[ManualReview]) -> str:
    return _csv([review.model_dump(mode="json") for review in reviews])


def evaluations_json(evaluations: list[ProjectEvaluation]) -> str:
    return json.dumps(
        [item.model_dump(mode="json") for item in evaluations],
        ensure_ascii=False,
        indent=2,
    )


def weekly_markdown(
    evaluations: list[ProjectEvaluation], ecosystem_context: str | None = None
) -> str:
    ranked = _ranked(evaluations)
    high = [
        item
        for item in ranked
        if (item.scorecard.overall_priority_score or 0) >= 70
    ]
    builders = list(
        dict.fromkeys(item.bundle.repository.owner_login for item in ranked[:5])
    )
    categories = list(
        dict.fromkeys(
            category
            for item in ranked
            if item.semantic_analysis
            for category in item.semantic_analysis.categories
        )
    )
    opportunities = [
        opportunity
        for item in ranked
        if item.semantic_analysis
        for opportunity in item.semantic_analysis.collaboration_opportunities
    ]
    risks = list(
        dict.fromkeys(tag for item in ranked for tag in item.scorecard.risk_tags)
    )
    history_available = any(item.growth.available for item in ranked)
    lines = [
        "# AI Builder Radar Weekly Report",
        "",
        "## 数据范围",
        f"- 项目数量：{len(evaluations)}",
        f"- 目标生态背景：{ecosystem_context or '未提供具体生态背景'}",
        "- 数据来源：GitHub公开REST API、本地历史快照及经原文校验的README语义分析。",
        "",
        "## 高优先级项目",
        *(_project_lines(high) or ["- 数据不足"]),
        "",
        "## 值得关注的Builder",
        *([f"- {name}" for name in builders] or ["- 数据不足"]),
        "",
        "## 新出现的技术方向",
        *([f"- {name}" for name in categories[:10]] or ["- 数据不足"]),
        "",
        "## 潜在合作线索",
        *([f"- {item}" for item in opportunities[:10]] or ["- 数据不足"]),
        "",
        "## 主要风险",
        *([f"- {item}" for item in risks[:15]] or ["- 数据不足"]),
        "",
        "## 数据不足说明",
        "- 高分但覆盖率低不代表结论可靠。",
        (
            "- 已存在至少一个项目的两个不同时间点快照，可展示对应区间变化。"
            if history_available
            else "- 当前没有足够的双时间点快照，因此不提供“本周增长最快”等结论。"
        ),
        "",
        "## 评分规则说明",
        "- 可评估总分 = 可用维度加权得分 ÷ 可用维度权重 × 100。",
        "- 当前Stars是累计值，不等于Star增速；完整规则见docs/scoring.md。",
        "",
        "> 本报告仅用于开发者生态初筛，不是投资或商业结论。",
    ]
    return "\n".join(lines)


def _ranked(evaluations: list[ProjectEvaluation]) -> list[ProjectEvaluation]:
    return sorted(
        evaluations,
        key=lambda item: item.scorecard.overall_priority_score
        if item.scorecard.overall_priority_score is not None
        else -1,
        reverse=True,
    )


def _project_lines(items: list[ProjectEvaluation]) -> list[str]:
    return [
        f"- [{item.bundle.repository.full_name}]({item.bundle.repository.repository_url})"
        f"：Priority {item.scorecard.overall_priority_score}/100，"
        f"Coverage {item.scorecard.data_coverage:.0%}"
        for item in items
    ]


def _csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
