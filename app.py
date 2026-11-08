"""Streamlit entry point for AI Builder Radar V0.2."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import streamlit as st

from config import ConfigurationError, get_settings
from database import RadarDatabase
from reports import (
    evaluations_json,
    manual_reviews_csv,
    outreach_csv,
    ranking_csv,
    weekly_markdown,
)
from schemas import ManualReview, OutreachRecord, ProjectEvaluation
from utils import discover_projects


st.set_page_config(page_title="AI Builder Radar", page_icon="📡", layout="wide")


def main() -> None:
    st.title("AI Builder Radar")
    st.caption("V0.2 · 透明评估AI项目、Builder执行力与生态合作线索")
    try:
        settings = get_settings()
        database = RadarDatabase(settings.database_path)
    except ConfigurationError as exc:
        st.error(str(exc))
        st.stop()

    with st.sidebar:
        st.subheader("配置状态")
        st.write("DeepSeek API：", "Configured" if settings.deepseek_configured else "Missing")
        st.write(
            "DeepSeek Model：",
            settings.deepseek_model if settings.deepseek_model_configured else "Missing",
        )
        st.write(
            "GitHub Token：",
            "Configured" if settings.github_authenticated else "Anonymous",
        )
        if not settings.deepseek_model_configured:
            st.warning("DEEPSEEK_MODEL未配置；请在.env中填写账户实际可用的模型。")
        if not settings.github_authenticated:
            st.info("匿名GitHub API额度较低，批量详情采集可能触发限流。")
        st.caption("页面、日志与Debug均不显示密钥或Token。")
        page = st.radio(
            "导航",
            ["Discover", "Ranking", "Project Detail", "Evaluation", "Outreach List"],
        )

    result = st.session_state.get("discovery_result")
    ecosystem_context = st.session_state.get("ecosystem_context", "")
    if page == "Discover":
        _discover_page(settings)
    elif page == "Ranking":
        _ranking_page(result, database, ecosystem_context)
    elif page == "Project Detail":
        _detail_page(result, database)
    elif page == "Evaluation":
        _evaluation_page(result, database)
    else:
        _outreach_page(result, database)


def _discover_page(settings: Any) -> None:
    st.header("Discover")
    st.write("客观指标由GitHub公开API与Python计算；语义判断由DeepSeek经LangChain完成。")
    with st.form("discovery_form"):
        keyword = st.text_input(
            "AI技术关键词", placeholder="RAG、AI Agent、AI Coding、LLM Evaluation"
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            limit = st.number_input("返回项目数量", 1, 10, 5)
            use_stars = st.checkbox("设置最低Star")
            min_stars = st.number_input(
                "最低Star", min_value=0, value=100, disabled=not use_stars
            )
        with col2:
            language = st.text_input("编程语言（可选）", placeholder="Python")
            use_date = st.checkbox("限制最近更新时间")
            updated_after = st.date_input(
                "最近Push不早于",
                value=date.today() - timedelta(days=180),
                disabled=not use_date,
            )
        with col3:
            ecosystem = st.text_area(
                "目标生态背景（可选）",
                placeholder="例如：AI模型平台、开发者工具平台、云计算平台",
            )
            enable_llm = st.checkbox("启用LLM深度分析", value=True)
        submitted = st.form_submit_button("Discover Projects", type="primary")

    if submitted:
        if not keyword.strip():
            st.warning("请输入AI技术关键词。")
            return
        if enable_llm and (
            not settings.deepseek_configured
            or not settings.deepseek_model_configured
        ):
            st.warning(
                "DeepSeek Key或模型名缺失：本次仍会采集和评分GitHub客观数据，"
                "但语义字段显示“数据不足”，不会生成替代分析。"
            )
        with st.status("正在采集公开数据并计算透明评分…", expanded=True) as status:
            result = discover_projects(
                keyword=keyword,
                limit=int(limit),
                min_stars=int(min_stars) if use_stars else None,
                language=language or None,
                updated_after=updated_after.isoformat() if use_date else None,
                ecosystem_context=ecosystem or None,
                enable_llm=enable_llm,
                settings=settings,
            )
            st.session_state["discovery_result"] = result
            st.session_state["ecosystem_context"] = ecosystem
            status.write(f"完成：{len(result.evaluations)}个项目。")
            status.update(label="查询完成", state="complete", expanded=False)

    result = st.session_state.get("discovery_result")
    if not result:
        st.info("尚未查询。首次查询不会有增长数据；需要后续不同时间点快照才能计算变化。")
        return
    _rate_limit(result.rate_limit)
    if result.errors:
        with st.expander(f"采集或分析提示（{len(result.errors)}）"):
            for error in result.errors:
                st.warning(error)
    if result.agent_message:
        st.subheader("LangChain Agent初筛")
        st.markdown(result.agent_message)
    st.subheader("项目概览")
    for item in _ranked(result.evaluations):
        _project_summary_card(item)
    _debug(result)


def _ranking_page(result: Any, database: RadarDatabase, ecosystem: str) -> None:
    st.header("Ranking")
    evaluations = result.evaluations if result else []
    if not evaluations:
        st.info("请先在Discover页面完成一次查询。")
        return
    col1, col2 = st.columns(2)
    with col1:
        sort_key = st.selectbox(
            "排序",
            ["Overall Priority", "Project Potential", "Builder Execution", "Data Coverage"],
        )
    with col2:
        minimum_coverage = st.slider("最低Data Coverage", 0.0, 1.0, 0.0, 0.05)
    rows = _ranking_rows(evaluations, sort_key, minimum_coverage)
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.warning("高分但覆盖率低，不代表结论可靠；当前Stars不等于Star增速。")
    st.subheader("导出")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            "下载排行榜CSV",
            ranking_csv(evaluations),
            "ai_builder_radar_ranking.csv",
            "text/csv",
        )
    with col2:
        st.download_button(
            "下载完整JSON",
            evaluations_json(evaluations),
            "ai_builder_radar_results.json",
            "application/json",
        )
    with col3:
        st.download_button(
            "下载Markdown周报",
            weekly_markdown(evaluations, ecosystem),
            "ai_builder_radar_weekly.md",
            "text/markdown",
        )
    reviews = database.get_manual_reviews()
    if reviews:
        st.download_button(
            "下载人工评价CSV",
            manual_reviews_csv(reviews),
            "ai_builder_radar_reviews.csv",
            "text/csv",
        )


def _detail_page(result: Any, database: RadarDatabase) -> None:
    st.header("Project Detail")
    evaluations = result.evaluations if result else []
    if not evaluations:
        st.info("请先在Discover页面完成一次查询。")
        return
    names = [item.bundle.repository.full_name for item in evaluations]
    selected = st.selectbox("选择项目", names)
    item = next(x for x in evaluations if x.bundle.repository.full_name == selected)
    repo, bundle, semantic = item.bundle.repository, item.bundle, item.semantic_analysis
    st.subheader(repo.full_name)
    st.markdown(f"[GitHub仓库]({repo.repository_url}) · [Builder公开主页]({repo.owner_profile_url})")
    st.caption(f"Builder类型：{'组织账号' if repo.owner_type == 'Organization' else repo.owner_type or '数据不足'}")
    cols = st.columns(5)
    cols[0].metric("Stars（累计）", _value(repo.stars))
    cols[1].metric("Forks（累计）", _value(repo.forks))
    cols[2].metric("Contributors", _value(bundle.contributors.contributors_count))
    cols[3].metric("Releases", _value(bundle.releases.releases_count))
    cols[4].metric("Coverage", f"{item.scorecard.data_coverage:.0%}")

    st.subheader("公开项目数据")
    st.write(repo.description or "数据不足")
    st.write(
        {
            "主语言": repo.primary_language or "数据不足",
            "Topics": repo.topics,
            "License": repo.license or "数据不足",
            "Homepage/Demo": repo.homepage or "数据不足",
            "最近Push": str(repo.pushed_at or "数据不足"),
            "最近Release": str(bundle.releases.latest_release_at or "数据不足"),
            "README长度": bundle.readme.length,
        }
    )
    st.subheader("README与语义分析")
    if item.semantic_error:
        st.warning(f"语义分析提示：{item.semantic_error}")
    _semantic_fields(semantic)

    st.subheader("分项评分与依据")
    st.dataframe(
        [
            {
                "Dimension": dimension.dimension_name,
                "Raw Score": dimension.raw_score if dimension.available else "数据不足",
                "Weight": dimension.weight,
                "Available": dimension.available,
                "Source Type": dimension.source_type,
                "Confidence": dimension.confidence,
                "Explanation": dimension.explanation,
                "Evidence": "; ".join(dimension.evidence),
            }
            for dimension in item.scorecard.dimensions
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.write("Risk Tags：", ", ".join(item.scorecard.risk_tags) or "无")

    st.subheader("Evidence")
    if semantic and semantic.evidence:
        for evidence in semantic.evidence:
            st.markdown(
                f"- **{evidence.claim}** · `{evidence.source}` · “{evidence.quote}”"
            )
    else:
        st.write("数据不足")

    st.subheader("历史快照与真实变化")
    if item.growth.available:
        st.success(
            f"{item.growth.start_at} → {item.growth.end_at}："
            f"Star变化 {item.growth.star_change}，Fork变化 {item.growth.fork_change}"
        )
    else:
        st.info(item.growth.reason)
    history = database.get_snapshots(repo.full_name)
    st.dataframe(
        [snapshot.model_dump(mode="json") for snapshot in history],
        use_container_width=True,
        hide_index=True,
    )


def _evaluation_page(result: Any, database: RadarDatabase) -> None:
    st.header("Evaluation")
    evaluations = result.evaluations if result else []
    if not evaluations:
        st.info("请先在Discover页面完成一次查询。")
    else:
        selected = st.selectbox(
            "项目", [item.bundle.repository.full_name for item in evaluations]
        )
        with st.form("manual_review"):
            relevant = st.radio("Relevant", ["Yes", "No"], horizontal=True)
            worth = st.radio("Worth Following", ["Yes", "No"], horizontal=True)
            priority = st.selectbox("Priority", ["High", "Medium", "Low"])
            notes = st.text_area("Notes")
            if st.form_submit_button("保存人工评价", type="primary"):
                database.save_manual_review(
                    ManualReview(
                        repo_full_name=selected,
                        relevant=relevant == "Yes",
                        worth_following=worth == "Yes",
                        priority=priority,
                        notes=notes,
                        reviewed_at=datetime.now(UTC),
                    )
                )
                st.success("人工评价已保存。")
    reviews = database.get_manual_reviews()
    ranked_names = [
        item.bundle.repository.full_name for item in _ranked(evaluations)
    ]
    precision = database.precision_at_10(ranked_names)
    st.metric("Precision@10", f"{precision:.0%}" if precision is not None else "数据不足")
    if precision is None:
        st.info("尚无足够人工标注数据")
    st.dataframe(
        [item.model_dump(mode="json") for item in reviews],
        use_container_width=True,
        hide_index=True,
    )


def _outreach_page(result: Any, database: RadarDatabase) -> None:
    st.header("Outreach List")
    st.caption("只管理公开主页和人工状态；第一版不会自动发送邮件或私信。")
    evaluations = result.evaluations if result else []
    records = {item.repo_full_name: item for item in database.get_outreach()}
    if evaluations:
        selected = st.selectbox(
            "项目", [item.bundle.repository.full_name for item in evaluations]
        )
        evaluation = next(
            item for item in evaluations if item.bundle.repository.full_name == selected
        )
        repo, semantic = evaluation.bundle.repository, evaluation.semantic_analysis
        existing = records.get(selected)
        with st.form("outreach_form"):
            status = st.selectbox(
                "Status",
                ["Not Reviewed", "Interested", "Contacted", "Replied", "Follow-up", "Closed"],
                index=(
                    ["Not Reviewed", "Interested", "Contacted", "Replied", "Follow-up", "Closed"].index(existing.status)
                    if existing else 0
                ),
            )
            notes = st.text_area("Notes", value=existing.notes if existing else "")
            if st.form_submit_button("保存外联状态"):
                database.save_outreach(
                    OutreachRecord(
                        repo_full_name=repo.full_name,
                        builder=repo.owner_login,
                        why_relevant=semantic.problem_value if semantic else None,
                        potential_collaboration=(
                            "; ".join(semantic.collaboration_opportunities)
                            if semantic else None
                        ),
                        suggested_outreach_angle=semantic.outreach_angle if semantic else None,
                        public_profile_url=repo.owner_profile_url,
                        status=status,
                        notes=notes,
                        updated_at=datetime.now(UTC),
                    )
                )
                st.success("状态已保存。")
    records_list = _merged_outreach_records(evaluations, database.get_outreach())
    st.dataframe(
        [item.model_dump(mode="json") for item in records_list],
        use_container_width=True,
        hide_index=True,
    )
    if records_list:
        st.download_button(
            "下载Builder外联清单CSV",
            outreach_csv(records_list),
            "ai_builder_radar_outreach.csv",
            "text/csv",
        )


def _project_summary_card(item: ProjectEvaluation) -> None:
    repo, score = item.bundle.repository, item.scorecard
    with st.container(border=True):
        st.markdown(f"### [{repo.full_name}]({repo.repository_url})")
        st.caption(
            f"Builder：{repo.owner_login}（{repo.owner_type or '类型未知'}） · "
            f"最近Push：{repo.pushed_at or '数据不足'}"
        )
        cols = st.columns(6)
        cols[0].metric("Stars", _value(repo.stars))
        cols[1].metric("Project Potential", _score(score.project_potential_score))
        cols[2].metric("Builder Execution", _score(score.builder_execution_score))
        cols[3].metric("Ecosystem Fit", _score(score.ecosystem_fit_score))
        cols[4].metric("Overall Priority", _score(score.overall_priority_score))
        cols[5].metric("Coverage / Confidence", f"{score.data_coverage:.0%} / {score.confidence:.2f}")
        st.write("风险：", ", ".join(score.risk_tags) or "无")
        if not item.growth.available:
            st.caption("增长：暂无历史快照。当前累计Stars不是Star增速。")


def _merged_outreach_records(
    evaluations: list[ProjectEvaluation], saved: list[OutreachRecord]
) -> list[OutreachRecord]:
    records = {item.repo_full_name: item for item in saved}
    for evaluation in evaluations:
        repo, semantic = evaluation.bundle.repository, evaluation.semantic_analysis
        if repo.full_name not in records:
            records[repo.full_name] = OutreachRecord(
                repo_full_name=repo.full_name,
                builder=repo.owner_login,
                why_relevant=semantic.problem_value if semantic else None,
                potential_collaboration=(
                    "; ".join(semantic.collaboration_opportunities)
                    if semantic else None
                ),
                suggested_outreach_angle=semantic.outreach_angle if semantic else None,
                public_profile_url=repo.owner_profile_url,
                updated_at=datetime.now(UTC),
            )
    return list(records.values())


def _semantic_fields(semantic: Any) -> None:
    if semantic is None:
        st.write("语义分析：数据不足")
        return
    fields = {
        "项目摘要": semantic.project_summary,
        "解决的问题": semantic.problem_solved,
        "目标用户": semantic.target_users,
        "技术方向": semantic.technical_stack,
        "技术差异化": semantic.technical_differentiation,
        "产品成熟度": semantic.product_maturity_explanation,
        "主要优势": semantic.strengths,
        "主要风险": semantic.risks,
        "生态适配": semantic.ecosystem_fit,
        "合作机会": semantic.collaboration_opportunities,
        "外联切入点": semantic.outreach_angle,
    }
    for label, value in fields.items():
        st.markdown(f"**{label}**：{value or '数据不足'}")


def _debug(result: Any) -> None:
    with st.expander("Agent Debug"):
        for index, event in enumerate(result.tool_events, start=1):
            st.markdown(f"**{index}. {event.tool} — {event.status}**")
            st.json(event.input)
            st.write("返回项目数量：", event.returned_count)
            if event.error:
                st.error(event.error)
        st.markdown("**最终消息**")
        st.text(result.agent_message or "LLM Agent未运行或未返回消息。")


def _rate_limit(rate_limit: Any) -> None:
    st.caption(
        "GitHub Rate Limit："
        f"{rate_limit.remaining if rate_limit.remaining is not None else '未知'} / "
        f"{rate_limit.limit if rate_limit.limit is not None else '未知'}，"
        f"重置时间：{rate_limit.reset_at or '未知'}"
    )


def _ranking_rows(
    evaluations: list[ProjectEvaluation], sort_key: str, minimum_coverage: float
) -> list[dict[str, Any]]:
    key_map = {
        "Overall Priority": lambda item: item.scorecard.overall_priority_score,
        "Project Potential": lambda item: item.scorecard.project_potential_score,
        "Builder Execution": lambda item: item.scorecard.builder_execution_score,
        "Data Coverage": lambda item: item.scorecard.data_coverage * 100,
    }
    filtered = [
        item for item in evaluations if item.scorecard.data_coverage >= minimum_coverage
    ]
    ordered = sorted(filtered, key=lambda item: key_map[sort_key](item) or -1, reverse=True)
    rows = []
    for rank, item in enumerate(ordered, 1):
        repo, score, semantic = (
            item.bundle.repository,
            item.scorecard,
            item.semantic_analysis,
        )
        rows.append(
            {
                "Rank": rank,
                "Project": repo.full_name,
                "Builder": repo.owner_login,
                "Category": (
                    ", ".join(semantic.categories[:2])
                    if semantic and semantic.categories
                    else ", ".join(repo.topics[:2]) or "数据不足"
                ),
                "Stars": repo.stars,
                "Recent Activity": repo.pushed_at,
                "Project Potential": _score(score.project_potential_score),
                "Builder Execution": _score(score.builder_execution_score),
                "Ecosystem Fit": _score(score.ecosystem_fit_score),
                "Overall Priority": _score(score.overall_priority_score),
                "Data Coverage": f"{score.data_coverage:.0%}",
                "Confidence": f"{score.confidence:.2f}",
                "Risk Tags": ", ".join(score.risk_tags),
            }
        )
    return rows


def _ranked(evaluations: list[ProjectEvaluation]) -> list[ProjectEvaluation]:
    return sorted(
        evaluations,
        key=lambda item: item.scorecard.overall_priority_score or -1,
        reverse=True,
    )


def _score(value: float | None) -> str:
    return f"{value:.1f}/100" if value is not None else "数据不足"


def _value(value: Any) -> Any:
    return value if value is not None else "数据不足"


if __name__ == "__main__":
    main()
