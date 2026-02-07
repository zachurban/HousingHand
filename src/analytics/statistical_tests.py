"""Statistical testing utilities for HousingHand analytics.

Provides t-tests, significance testing, effect size calculations, and
confidence interval computation used across reform impact analysis and
peer benchmarking modules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TypedDict

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class TTestResult(TypedDict):
    """Result of an independent two-sample t-test."""

    t_statistic: float
    p_value: float
    degrees_of_freedom: float
    mean_a: float
    mean_b: float
    std_a: float
    std_b: float
    n_a: int
    n_b: int
    significant: bool
    alpha: float
    cohens_d: float
    confidence_interval_diff: tuple[float, float]


class PairedTTestResult(TypedDict):
    """Result of a paired t-test."""

    t_statistic: float
    p_value: float
    degrees_of_freedom: int
    mean_diff: float
    std_diff: float
    n: int
    significant: bool
    alpha: float
    confidence_interval_diff: tuple[float, float]


class MannWhitneyResult(TypedDict):
    """Result of a Mann-Whitney U test (non-parametric alternative)."""

    u_statistic: float
    p_value: float
    n_a: int
    n_b: int
    significant: bool
    alpha: float
    rank_biserial_r: float


class ConfidenceIntervalResult(TypedDict):
    """A confidence interval for a sample mean."""

    mean: float
    lower: float
    upper: float
    confidence_level: float
    margin_of_error: float
    n: int


class NormalityTestResult(TypedDict):
    """Result from a Shapiro-Wilk normality test."""

    statistic: float
    p_value: float
    is_normal: bool
    alpha: float
    n: int


class EffectSizeResult(TypedDict):
    """Cohen's d effect size with interpretation."""

    cohens_d: float
    interpretation: str  # "negligible", "small", "medium", "large"
    pooled_std: float


# ---------------------------------------------------------------------------
# Core statistical functions
# ---------------------------------------------------------------------------


def independent_ttest(
    sample_a: list[float] | np.ndarray,
    sample_b: list[float] | np.ndarray,
    alpha: float = 0.05,
    equal_var: bool = False,
) -> TTestResult:
    """Perform an independent two-sample t-test (Welch's by default).

    Compares means of two independent groups and determines whether the
    observed difference is statistically significant.

    Args:
        sample_a: Observations from group A (e.g. pre-reform durations).
        sample_b: Observations from group B (e.g. post-reform durations).
        alpha: Significance threshold (default 0.05).
        equal_var: If True, use Student's t-test (assumes equal variance).
            If False, use Welch's t-test (default, more robust).

    Returns:
        TTestResult dict with test statistics, p-value, significance flag,
        Cohen's d, and a confidence interval for the mean difference.

    Raises:
        ValueError: If either sample has fewer than 2 observations.
    """
    a = np.asarray(sample_a, dtype=float)
    b = np.asarray(sample_b, dtype=float)

    # Drop NaN values
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]

    if len(a) < 2 or len(b) < 2:
        raise ValueError(
            f"Each sample must have at least 2 observations. "
            f"Got n_a={len(a)}, n_b={len(b)}."
        )

    t_stat, p_value = stats.ttest_ind(a, b, equal_var=equal_var)

    # Welch-Satterthwaite degrees of freedom
    if equal_var:
        df = float(len(a) + len(b) - 2)
    else:
        df = _welch_df(a, b)

    effect = cohens_d(a, b)

    # Confidence interval for the difference in means
    mean_diff = float(np.mean(a) - np.mean(b))
    se_diff = np.sqrt(np.var(a, ddof=1) / len(a) + np.var(b, ddof=1) / len(b))
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    ci_lower = mean_diff - t_crit * se_diff
    ci_upper = mean_diff + t_crit * se_diff

    return TTestResult(
        t_statistic=float(t_stat),
        p_value=float(p_value),
        degrees_of_freedom=float(df),
        mean_a=float(np.mean(a)),
        mean_b=float(np.mean(b)),
        std_a=float(np.std(a, ddof=1)),
        std_b=float(np.std(b, ddof=1)),
        n_a=len(a),
        n_b=len(b),
        significant=bool(p_value < alpha),
        alpha=alpha,
        cohens_d=effect["cohens_d"],
        confidence_interval_diff=(float(ci_lower), float(ci_upper)),
    )


def paired_ttest(
    before: list[float] | np.ndarray,
    after: list[float] | np.ndarray,
    alpha: float = 0.05,
) -> PairedTTestResult:
    """Perform a paired (dependent) t-test on matched observations.

    Use this when the same projects are measured before and after an
    intervention.

    Args:
        before: Pre-intervention measurements.
        after: Post-intervention measurements.
        alpha: Significance threshold.

    Returns:
        PairedTTestResult dict.

    Raises:
        ValueError: If sample sizes do not match or are < 2.
    """
    b = np.asarray(before, dtype=float)
    a = np.asarray(after, dtype=float)

    # Drop pairs where either value is NaN
    mask = ~(np.isnan(b) | np.isnan(a))
    b = b[mask]
    a = a[mask]

    if len(b) != len(a):
        raise ValueError("Before and after samples must be the same length.")
    if len(b) < 2:
        raise ValueError(f"Need at least 2 paired observations. Got {len(b)}.")

    diffs = b - a
    t_stat, p_value = stats.ttest_rel(b, a)
    df = len(diffs) - 1

    mean_diff = float(np.mean(diffs))
    std_diff = float(np.std(diffs, ddof=1))
    se_diff = std_diff / np.sqrt(len(diffs))
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    ci_lower = mean_diff - t_crit * se_diff
    ci_upper = mean_diff + t_crit * se_diff

    return PairedTTestResult(
        t_statistic=float(t_stat),
        p_value=float(p_value),
        degrees_of_freedom=df,
        mean_diff=mean_diff,
        std_diff=std_diff,
        n=len(diffs),
        significant=bool(p_value < alpha),
        alpha=alpha,
        confidence_interval_diff=(float(ci_lower), float(ci_upper)),
    )


def mann_whitney_test(
    sample_a: list[float] | np.ndarray,
    sample_b: list[float] | np.ndarray,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> MannWhitneyResult:
    """Perform Mann-Whitney U test (non-parametric alternative to t-test).

    Preferred when data is non-normal or ordinal, which is common for
    housing development timeline durations that are right-skewed.

    Args:
        sample_a: Observations from group A.
        sample_b: Observations from group B.
        alpha: Significance threshold.
        alternative: 'two-sided', 'less', or 'greater'.

    Returns:
        MannWhitneyResult dict.
    """
    a = np.asarray(sample_a, dtype=float)
    b = np.asarray(sample_b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]

    if len(a) < 1 or len(b) < 1:
        raise ValueError(
            f"Each sample must have at least 1 observation. "
            f"Got n_a={len(a)}, n_b={len(b)}."
        )

    u_stat, p_value = stats.mannwhitneyu(a, b, alternative=alternative)

    # Rank-biserial correlation as effect size
    n_total = len(a) * len(b)
    r_rb = 1 - (2 * u_stat) / n_total if n_total > 0 else 0.0

    return MannWhitneyResult(
        u_statistic=float(u_stat),
        p_value=float(p_value),
        n_a=len(a),
        n_b=len(b),
        significant=bool(p_value < alpha),
        alpha=alpha,
        rank_biserial_r=float(r_rb),
    )


def cohens_d(
    sample_a: list[float] | np.ndarray,
    sample_b: list[float] | np.ndarray,
) -> EffectSizeResult:
    """Calculate Cohen's d effect size for two independent samples.

    Uses the pooled standard deviation. Interpretation follows
    conventional thresholds: |d| < 0.2 negligible, < 0.5 small,
    < 0.8 medium, >= 0.8 large.

    Args:
        sample_a: Observations from group A.
        sample_b: Observations from group B.

    Returns:
        EffectSizeResult with Cohen's d and a textual interpretation.
    """
    a = np.asarray(sample_a, dtype=float)
    b = np.asarray(sample_b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]

    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return EffectSizeResult(
            cohens_d=0.0,
            interpretation="insufficient_data",
            pooled_std=0.0,
        )

    var_a = np.var(a, ddof=1)
    var_b = np.var(b, ddof=1)
    pooled_std = float(np.sqrt(((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2)))

    if pooled_std == 0.0:
        d = 0.0
    else:
        d = float((np.mean(a) - np.mean(b)) / pooled_std)

    abs_d = abs(d)
    if abs_d < 0.2:
        interp = "negligible"
    elif abs_d < 0.5:
        interp = "small"
    elif abs_d < 0.8:
        interp = "medium"
    else:
        interp = "large"

    return EffectSizeResult(
        cohens_d=d,
        interpretation=interp,
        pooled_std=pooled_std,
    )


def confidence_interval(
    sample: list[float] | np.ndarray,
    confidence_level: float = 0.95,
) -> ConfidenceIntervalResult:
    """Compute a confidence interval for the population mean.

    Uses the t-distribution which is appropriate for small sample sizes
    typical in housing project datasets.

    Args:
        sample: Array of observations.
        confidence_level: Desired confidence (default 0.95 for 95% CI).

    Returns:
        ConfidenceIntervalResult with lower/upper bounds and margin of error.
    """
    data = np.asarray(sample, dtype=float)
    data = data[~np.isnan(data)]

    if len(data) < 2:
        raise ValueError(f"Need at least 2 observations. Got {len(data)}.")

    n = len(data)
    mean = float(np.mean(data))
    se = float(stats.sem(data))
    df = n - 1
    t_crit = stats.t.ppf((1 + confidence_level) / 2, df)
    margin = t_crit * se

    return ConfidenceIntervalResult(
        mean=mean,
        lower=mean - margin,
        upper=mean + margin,
        confidence_level=confidence_level,
        margin_of_error=margin,
        n=n,
    )


def test_normality(
    sample: list[float] | np.ndarray,
    alpha: float = 0.05,
) -> NormalityTestResult:
    """Test whether a sample follows a normal distribution (Shapiro-Wilk).

    Housing timeline durations are often right-skewed, so this test helps
    decide whether to use parametric (t-test) or non-parametric
    (Mann-Whitney) methods.

    Args:
        sample: Array of observations.
        alpha: Significance threshold for rejecting normality.

    Returns:
        NormalityTestResult with test statistic, p-value, and boolean flag.
    """
    data = np.asarray(sample, dtype=float)
    data = data[~np.isnan(data)]

    if len(data) < 3:
        raise ValueError(f"Shapiro-Wilk requires at least 3 observations. Got {len(data)}.")

    # Shapiro-Wilk has a sample size limit of 5000
    if len(data) > 5000:
        logger.warning(
            "Sample size %d exceeds Shapiro-Wilk limit; sub-sampling to 5000.", len(data)
        )
        rng = np.random.default_rng(42)
        data = rng.choice(data, size=5000, replace=False)

    stat, p_value = stats.shapiro(data)

    return NormalityTestResult(
        statistic=float(stat),
        p_value=float(p_value),
        is_normal=bool(p_value >= alpha),
        alpha=alpha,
        n=len(data),
    )


def select_and_run_test(
    sample_a: list[float] | np.ndarray,
    sample_b: list[float] | np.ndarray,
    alpha: float = 0.05,
    normality_alpha: float = 0.05,
) -> dict:
    """Automatically select the appropriate test based on data normality.

    Runs Shapiro-Wilk on both samples. If both pass normality, uses
    Welch's t-test. Otherwise, falls back to Mann-Whitney U.

    Args:
        sample_a: First group of observations.
        sample_b: Second group of observations.
        alpha: Significance threshold for the main test.
        normality_alpha: Significance threshold for normality pre-test.

    Returns:
        Dict with 'test_used' ('ttest' | 'mann_whitney'), 'result' (the
        typed dict), and 'normality_a' / 'normality_b' NormalityTestResults.
    """
    a = np.asarray(sample_a, dtype=float)
    b = np.asarray(sample_b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]

    norm_a = None
    norm_b = None
    use_parametric = True

    # Only test normality if samples are large enough
    if len(a) >= 3:
        norm_a = test_normality(a, alpha=normality_alpha)
        if not norm_a["is_normal"]:
            use_parametric = False
    else:
        # Too few observations; prefer non-parametric
        use_parametric = False

    if len(b) >= 3:
        norm_b = test_normality(b, alpha=normality_alpha)
        if not norm_b["is_normal"]:
            use_parametric = False
    else:
        use_parametric = False

    if use_parametric:
        result = independent_ttest(a, b, alpha=alpha, equal_var=False)
        test_name = "ttest"
    else:
        result = mann_whitney_test(a, b, alpha=alpha)
        test_name = "mann_whitney"

    return {
        "test_used": test_name,
        "result": result,
        "normality_a": norm_a,
        "normality_b": norm_b,
    }


def percentile_rank(value: float, distribution: list[float] | np.ndarray) -> float:
    """Return the percentile rank of a value within a distribution.

    Args:
        value: The observation to rank.
        distribution: Reference distribution to rank against.

    Returns:
        Float between 0.0 and 100.0 representing the percentile.
    """
    dist = np.asarray(distribution, dtype=float)
    dist = dist[~np.isnan(dist)]
    if len(dist) == 0:
        return 50.0
    return float(stats.percentileofscore(dist, value, kind="rank"))


def z_score(value: float, mean: float, std: float) -> float:
    """Compute the z-score of an observation.

    Args:
        value: Observed value.
        mean: Population or sample mean.
        std: Population or sample standard deviation.

    Returns:
        Z-score as a float. Returns 0.0 if std is zero.
    """
    if std == 0.0:
        return 0.0
    return (value - mean) / std


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _welch_df(a: np.ndarray, b: np.ndarray) -> float:
    """Welch-Satterthwaite approximation for degrees of freedom."""
    var_a = np.var(a, ddof=1)
    var_b = np.var(b, ddof=1)
    n_a = len(a)
    n_b = len(b)

    num = (var_a / n_a + var_b / n_b) ** 2
    denom = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)

    if denom == 0:
        return float(n_a + n_b - 2)
    return float(num / denom)
