"""
Shared confidence-interval helper.

The manuscript reports means over 3 or 5 seeds and calls the half-width a "95% confidence
half-width". At these sample sizes the normal-approximation critical value 1.96 understates the
half-width: the correct critical value for a mean of n samples with unknown population variance is
the two-tailed 97.5th percentile of the Student-t distribution with n-1 degrees of freedom, which
is materially larger for small n (t=4.303 at df=2 vs. 1.96; t=2.776 at df=4 vs. 1.96).

T_CRIT_975 is the standard textbook table for the two-tailed 95% critical value (df 1-30);
beyond df=30 the t-distribution has converged closely enough to the normal that 1.96 is used, which
is the asymptotic case of the same distribution rather than a different method.
"""
import math
import statistics as st

T_CRIT_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
    10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110,
    18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def t_crit(df):
    if df < 1:
        raise ValueError(f"degrees of freedom must be >= 1, got {df}")
    return T_CRIT_975.get(df, 1.96)


def ci95(xs):
    """Mean and Student-t 95% confidence half-width over xs (half-width 0 for n<2)."""
    xs = list(xs)
    n = len(xs)
    if n < 2:
        return (xs[0] if xs else 0.0, 0.0)
    m = st.mean(xs)
    sd = st.stdev(xs)
    return (m, t_crit(n - 1) * sd / math.sqrt(n))
