# RL Pricing Asset Slots

Drop licensed image assets into this folder to enable full branding in the Streamlit app.

## Required / optional files

- `steeden_ball.png`
  - Used as the browser tab icon and the animated pricing loader ball.
- `super_league_logo.png`
  - Displayed in the top-right of the hero section.
- `hero_players.jpg`
  - Opening hero image at the top of the page.

## Team emblems

Put one image per team in `teams/` using a slugged filename based on the team name:

- lowercase
- non-alphanumeric chars replaced with `_`

Examples:

- `Leeds Rhinos` -> `teams/leeds_rhinos.png`
- `Wigan Warriors` -> `teams/wigan_warriors.png`
- `Hull KR` -> `teams/hull_kr.png`

Supported formats: `.png`, `.webp`, `.jpg`, `.jpeg`, `.svg`

If a team logo is missing, the app shows a fallback initials badge.
