# HousingHand Analytics Methodology

## Pipeline Health Assessment

Each project receives a weighted health score (0-100):

| Component | Weight | Description |
|-----------|--------|-------------|
| Timeline | 30% | Adherence to peer benchmark duration |
| Budget | 25% | Variance from original budget |
| Funding | 20% | Funding gap as % of total cost |
| Risk | 15% | Accumulated risk factor count |
| Team | 10% | Team stability indicators |

**Health statuses:**
- On Track (80-100)
- At Risk (60-79)
- Delayed (40-59)
- Stalled (0-39)

## Bottleneck Detection

Identifies systematic barriers across jurisdictions by:

1. **Stage analysis** - Which pipeline stage has the longest delays vs national benchmarks
2. **Topic analysis** - Which regulatory requirements cause the most friction (cross-referenced with HousingLens)
3. **Temporal analysis** - Whether timelines are improving, worsening, or stable
4. **Peer comparison** - How jurisdiction compares to similar jurisdictions

## Timeline Prediction

Uses a Random Forest Regression model trained on completed projects.

**Features:**
- Project characteristics (units, AMI mix, building type, stories)
- Jurisdiction friction scores (from HousingLens)
- Market conditions (construction cost index, interest rates)
- Historical peer project timelines
- Seasonal factors

**Output:** Predicted months for each remaining stage with 80% confidence intervals.

## Policy Reform Impact

Uses difference-in-differences methodology:
1. Compare pre-reform and post-reform project timelines
2. Control for market conditions and project characteristics
3. Statistical significance via Welch's t-test (p < 0.05)
4. Effectiveness categories: highly effective (>30% improvement), effective (>15%), marginal (>5%), ineffective

## Portfolio Intelligence

Aggregates project data across dimensions:
- Pipeline snapshot (units by stage)
- Delivery forecast (units by quarter)
- Health distribution
- Velocity metrics (annualized production rates)
- Funding gap analysis
- Geographic distribution
