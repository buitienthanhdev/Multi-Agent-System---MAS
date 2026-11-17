"""Measurement & Closed-Loop Optimization Layer (Step 5 & Step 6).

Provides:
- Statistical Difference-in-Differences (DiD) with:
  1. Pre-campaign Parallel Trends test (OLS slope difference t-statistic & p-value approximation)
  2. Welch's two-sample t-test & 95% confidence interval on daily treated-minus-control lift
  3. Full funnel KPI calculation: Impressions -> Clicks (CTR) -> Leads -> Qualified Leads (Lead Quality Rate) ->
     Orders (CVR) -> Gross Revenue -> Gross Profit -> Net Incremental ROI (iROAS & Net Margin after Ad Spend).
- Closed-loop feedback to Planner (`closed_loop_replan`): evaluates measured KPIs against Mission Contract and
  automatically updates the Plan / Decisions with data-driven next actions (scale, reallocate channel, or halt)."""
from __future__ import annotations

import math
import statistics
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.models import BusinessKPIEvent, Decision, Mission, Plan, Task


def _ols_slope(ys: list[float]) -> tuple[float, float]:
    """Return (slope, standard_error_of_slope) for y_t over t = 0..n-1."""
    n = len(ys)
    if n < 3:
        return 0.0, 0.0
    xs = list(range(n))
    mx = (n - 1) / 2.0
    my = statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    s2 = sum(r * r for r in residuals) / max(1, n - 2)
    se = math.sqrt(s2 / sxx) if sxx > 0 else 0.0
    return slope, se


def _normal_two_sided_p(t_abs: float) -> float:
    """Two-sided p-value using complementary error function (normal approximation)."""
    return float(math.erfc(t_abs / math.sqrt(2.0)))


def _daily_revenue_by_date(rows: list[BusinessKPIEvent]) -> list[tuple[str, int]]:
    by_day: dict[str, int] = {}
    for e in rows:
        by_day[e.event_date] = by_day.get(e.event_date, 0) + int(e.revenue_minor)
    return sorted(by_day.items(), key=lambda x: x[0])


def analyze_business_kpis(events: list[BusinessKPIEvent]) -> dict[str, Any]:
    pre_t = [e for e in events if e.period == "pre_campaign" and e.cohort == "treated"]
    pre_c = [e for e in events if e.period == "pre_campaign" and e.cohort == "control"]
    post_t = [e for e in events if e.period == "campaign" and e.cohort == "treated"]
    post_c = [e for e in events if e.period == "campaign" and e.cohort == "control"]

    pre_t_daily = _daily_revenue_by_date(pre_t)
    pre_c_daily = _daily_revenue_by_date(pre_c)
    post_t_daily = _daily_revenue_by_date(post_t)
    post_c_daily = _daily_revenue_by_date(post_c)

    # 1. Parallel trends test on pre-campaign daily difference (treated_t - control_t)
    n_pre = min(len(pre_t_daily), len(pre_c_daily))
    pre_diffs = [float(pre_t_daily[i][1] - pre_c_daily[i][1]) for i in range(n_pre)]
    slope_diff, se_slope = _ols_slope(pre_diffs)
    pt_tstat = abs(slope_diff / se_slope) if se_slope > 0 else 0.0
    pt_pvalue = round(_normal_two_sided_p(pt_tstat), 4)
    parallel_trends_passed = pt_pvalue >= 0.05

    # 2. Difference-in-Differences & statistical significance
    n_post = min(len(post_t_daily), len(post_c_daily))
    post_diffs = [float(post_t_daily[i][1] - post_c_daily[i][1]) for i in range(n_post)]

    mean_pre_diff = statistics.fmean(pre_diffs) if pre_diffs else 0.0
    mean_post_diff = statistics.fmean(post_diffs) if post_diffs else 0.0
    daily_did = mean_post_diff - mean_pre_diff
    total_incremental_minor = int(round(daily_did * n_post))

    var_pre = statistics.variance(pre_diffs) if len(pre_diffs) > 1 else 0.0
    var_post = statistics.variance(post_diffs) if len(post_diffs) > 1 else 0.0
    se_daily_did = math.sqrt((var_pre / max(1, n_pre)) + (var_post / max(1, n_post)))
    se_total_did = se_daily_did * n_post
    t_stat_did = (daily_did / se_daily_did) if se_daily_did > 0 else 0.0
    p_value_did = round(_normal_two_sided_p(abs(t_stat_did)), 4)
    ci95_half = int(round(1.96 * se_total_did))

    # 3. Full Funnel & Unit Economics in Campaign Treated Cohort
    impressions = sum(e.impressions for e in post_t)
    clicks = sum(e.clicks for e in post_t)
    leads = sum(e.leads for e in post_t)
    qualified_leads = sum(e.qualified_leads for e in post_t)
    orders = sum(e.orders for e in post_t)
    gross_revenue_minor = sum(e.revenue_minor for e in post_t)
    cogs_minor = sum(e.cogs_minor for e in post_t)
    ad_spend_minor = sum(e.ad_spend_minor for e in post_t)
    gross_profit_minor = gross_revenue_minor - cogs_minor

    # Estimate incremental gross profit using observed gross margin ratio
    margin_ratio = (gross_profit_minor / gross_revenue_minor) if gross_revenue_minor > 0 else 0.0
    incremental_profit_minor = int(round(total_incremental_minor * margin_ratio)) - ad_spend_minor
    iroas = round(total_incremental_minor / ad_spend_minor, 2) if ad_spend_minor > 0 else None

    # Channel breakdown
    by_channel: dict[str, dict[str, Any]] = {}
    for e in post_t:
        ch = by_channel.setdefault(
            e.channel,
            {"impressions": 0, "clicks": 0, "leads": 0, "qualified_leads": 0, "orders": 0, "revenue_minor": 0, "ad_spend_minor": 0},
        )
        ch["impressions"] += e.impressions
        ch["clicks"] += e.clicks
        ch["leads"] += e.leads
        ch["qualified_leads"] += e.qualified_leads
        ch["orders"] += e.orders
        ch["revenue_minor"] += e.revenue_minor
        ch["ad_spend_minor"] += e.ad_spend_minor
    for ch_name, ch in by_channel.items():
        ch["lead_quality_rate"] = round(ch["qualified_leads"] / ch["leads"], 3) if ch["leads"] else 0.0
        ch["cvr_from_lead"] = round(ch["orders"] / ch["leads"], 3) if ch["leads"] else 0.0
        ch["roas"] = round(ch["revenue_minor"] / ch["ad_spend_minor"], 2) if ch["ad_spend_minor"] else None

    confounders = sorted({e.confounder_note for e in post_t + post_c if e.confounder_note})

    return {
        "n_pre_days": n_pre,
        "n_campaign_days": n_post,
        "baseline_30d_treated_minor": sum(v for _, v in pre_t_daily[-30:]),
        "gross_revenue_minor": gross_revenue_minor,
        "cogs_minor": cogs_minor,
        "gross_profit_minor": gross_profit_minor,
        "gross_margin_ratio": round(margin_ratio, 4),
        "ad_spend_minor": ad_spend_minor,
        "funnel": {
            "impressions": impressions,
            "clicks": clicks,
            "ctr": round(clicks / impressions, 4) if impressions else 0.0,
            "leads": leads,
            "qualified_leads": qualified_leads,
            "lead_quality_rate": round(qualified_leads / leads, 4) if leads else 0.0,
            "orders": orders,
            "lead_to_order_cvr": round(orders / leads, 4) if leads else 0.0,
            "cac_minor": int(round(ad_spend_minor / orders)) if orders else None,
        },
        "did_inference": {
            "parallel_trends_slope_diff_minor_per_day": round(slope_diff, 2),
            "parallel_trends_pvalue": pt_pvalue,
            "parallel_trends_passed": parallel_trends_passed,
            "incremental_revenue_minor": total_incremental_minor,
            "ci95_range_minor": [total_incremental_minor - ci95_half, total_incremental_minor + ci95_half],
            "uncertainty_2sd_minor": ci95_half,
            "t_statistic": round(t_stat_did, 3),
            "p_value": p_value_did,
            "statistically_significant_95": p_value_did < 0.05 and parallel_trends_passed,
        },
        "roi": {
            "incremental_roas": iroas,
            "net_incremental_profit_after_spend_minor": incremental_profit_minor,
        },
        "by_channel": by_channel,
        "observed_confounders": confounders,
    }


def closed_loop_replan(s: Session, mission: Mission, kpi_summary: dict[str, Any]) -> dict[str, Any]:
    """Feed measured business outcomes back into Planner & Decision log to adapt strategy automatically
    within authorized boundaries (never self-approving external spend)."""
    did = kpi_summary["did_inference"]
    roi = kpi_summary["roi"]
    by_channel = kpi_summary.get("by_channel", {})

    best_channel = None
    best_lq = -1.0
    for ch_name, ch_stats in by_channel.items():
        if ch_stats.get("lead_quality_rate", 0.0) > best_lq:
            best_lq = ch_stats["lead_quality_rate"]
            best_channel = ch_name

    if not did["parallel_trends_passed"]:
        action_code = "hold_and_recalibrate_control"
        summary = (
            f"Cảnh báo kiểm định Parallel Trends (p={did['parallel_trends_pvalue']} < 0.05): "
            "Nhóm đối chứng lệch xu hướng nền, tạm dừng đề xuất mở rộng ngân sách và yêu cầu chọn lại khu vực đối chứng."
        )
    elif did["statistically_significant_95"] and (roi["net_incremental_profit_after_spend_minor"] or 0) > 0:
        action_code = "propose_scale_winning_channel"
        summary = (
            f"Kết quả kinh doanh có ý nghĩa thống kê (p={did['p_value']}, iROAS={roi['incremental_roas']}x, "
            f"lợi nhuận tăng thêm ròng={roi['net_incremental_profit_after_spend_minor']:,} ₫). "
            f"Đề xuất bước tiếp theo: dịch chuyển trọng tâm sang kênh '{best_channel}' (Lead Quality={best_lq:.1%})."
        )
    else:
        action_code = "iterate_creative_and_offer"
        summary = (
            f"Mức tăng doanh thu chưa đạt ngưỡng lợi nhuận ròng có ý nghĩa thống kê (p={did['p_value']}). "
            "Đề xuất giữ nguyên trần chi tiêu, thử nghiệm lại thông điệp tư vấn kỹ thuật."
        )

    dec = Decision(
        mission_id=mission.id,
        kind="closed_loop_optimization",
        summary=summary,
        rationale=(
            f"Dựa trên DiD={did['incremental_revenue_minor']:,} ₫ (95% CI {did['ci95_range_minor']}), "
            f"parallel_trends_passed={did['parallel_trends_passed']}, funnel={kpi_summary['funnel']}."
        ),
        made_by="closed_loop_optimizer_v1",
        data={"action_code": action_code, "best_channel": best_channel, "kpi_summary": kpi_summary},
    )
    s.add(dec)
    s.flush()
    return {"decision_id": dec.id, "action_code": action_code, "summary": summary, "best_channel": best_channel}
