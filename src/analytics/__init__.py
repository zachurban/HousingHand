"""HousingHand Analytics Engine.

Provides pipeline health assessment, bottleneck detection, timeline
prediction, policy reform impact measurement, portfolio intelligence,
peer benchmarking, and statistical testing utilities.
"""

from src.analytics.bottleneck_detection import (
    detect_jurisdiction_bottlenecks,
    detect_systemic_bottlenecks,
    identify_stage_chokepoints,
)
from src.analytics.health_assessment import (
    assess_batch_health,
    assess_project_health,
    assess_project_health_and_persist,
)
from src.analytics.peer_benchmarking import (
    compare_project_to_peers,
    compute_peer_benchmarks,
    find_peer_group,
    refresh_peer_group_stats,
)
from src.analytics.portfolio_intelligence import (
    generate_and_persist_dashboard,
    generate_funder_view,
    generate_pha_view,
    generate_portfolio_dashboard,
    generate_state_view,
)
from src.analytics.reform_impact import (
    build_reform_time_series,
    compare_reforms_in_jurisdiction,
    measure_reform_impact,
    measure_reform_impact_and_persist,
)
from src.analytics.statistical_tests import (
    cohens_d,
    confidence_interval,
    independent_ttest,
    mann_whitney_test,
    paired_ttest,
    percentile_rank,
    select_and_run_test,
    test_normality,
    z_score,
)
from src.analytics.timeline_prediction import (
    predict_batch_timelines,
    predict_from_friction_score,
    predict_project_timeline,
)

__all__ = [
    # Health Assessment
    "assess_project_health",
    "assess_project_health_and_persist",
    "assess_batch_health",
    # Bottleneck Detection
    "detect_jurisdiction_bottlenecks",
    "detect_systemic_bottlenecks",
    "identify_stage_chokepoints",
    # Timeline Prediction
    "predict_project_timeline",
    "predict_batch_timelines",
    "predict_from_friction_score",
    # Reform Impact
    "measure_reform_impact",
    "measure_reform_impact_and_persist",
    "compare_reforms_in_jurisdiction",
    "build_reform_time_series",
    # Portfolio Intelligence
    "generate_portfolio_dashboard",
    "generate_and_persist_dashboard",
    "generate_funder_view",
    "generate_pha_view",
    "generate_state_view",
    # Peer Benchmarking
    "find_peer_group",
    "compute_peer_benchmarks",
    "compare_project_to_peers",
    "refresh_peer_group_stats",
    # Statistical Tests
    "independent_ttest",
    "paired_ttest",
    "mann_whitney_test",
    "cohens_d",
    "confidence_interval",
    "test_normality",
    "select_and_run_test",
    "percentile_rank",
    "z_score",
]
