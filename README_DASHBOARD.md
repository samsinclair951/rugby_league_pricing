# Pricing dashboard scaffold

Copy the `app/` folder into the repo root, replacing/merging with the existing `app/` folder.

Run from the repo root:

```bash
uv run streamlit run app/home.py
```

The dashboard expects:

- `fixtures` with `fixture_id`, `match_date`, `kick_off`, `home_team_id`, `away_team_id`
- `teams.canonical_name`
- `results` with final scores
- either `expected_score_predictions` or `expected_scores`
- `historical_score_matrices.probability_matrix`
- the pricing classes already created under `rugby_league_pricing.pricing.true_prices`

The totals pricer is assumed to use the same constructor pattern as the handicap pricer:

```python
MainlineTotalsPricer(
    score_matrix=score_matrix,
    expected_home_score=expected_home_score,
    expected_away_score=expected_away_score,
    line_range=20,
)
```

and expose `.mainline` and `.price_all()`.
