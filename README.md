# We're Not Wrexham ⚽ calendar

Auto-updating calendar of We're Not Wrexham's Mid State Sports Leagues rec soccer games, rebuilt every 6 hours by GitHub Actions.

## Subscribe

- **iPhone / Mac:** open `webcal://thepete.github.io/wnw-calendar/were-not-wrexham.ics`
- **Google Calendar:** Other calendars **+** → From URL → `https://thepete.github.io/wnw-calendar/were-not-wrexham.ics` (Google refreshes every 12–24 hours)
- **Outlook:** Add calendar → Subscribe from web → same `https://` link

Use *subscribe*, not *import*; an imported copy won't update.

## What's in it

- Title: `⚽ WNW (#8) vs AFC Nashville City United (#12) · Field 4` (current rank in our group), then `⚽ WNW 5–6 Wednesday Meows · Field 3` once the score is posted (our score first).
- Location: the venue's street address, for one-tap directions. Event notes have the opponent's full name, field, league, and game number.
- No reminders (set `ALERT_BEFORE` in the script to add one).

## How it works

- **New seasons are found automatically.** The script reads midstatesportsleagues.com/soccer/, opens every league page, and looks for the team in each league's TourneyMachine schedule. No URL changes needed as long as the team keeps its name.
- Between seasons the calendar is left as is, and past games stay in it.
- Settings at the top of `scripts/build_wrexham_calendar.py`: `TEAM_NAME`, `SHORT_NAME`, `LEAGUE_URLS` (pin a league page if discovery ever misses), `VENUE_ADDRESSES`, `ALERT_BEFORE`.

## Setup (one time)

1. **Settings → Actions → General → Workflow permissions:** Read and write. Save.
2. **Settings → Pages:** Deploy from a branch, `main`, folder `/docs`. Save.
