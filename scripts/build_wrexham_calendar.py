#!/usr/bin/env python3
"""Build an .ics calendar of We're Not Wrexham's rec league games.

Mid State Sports Leagues posts each season's schedule as a TourneyMachine
embed on a league page (e.g. /soccer/late-fall-wednesday-soccer/). Those pages
change every season, so by default this script finds the team on its own:

  1. read the soccer index page and collect every league page it links to
  2. pull the TourneyMachine tournament id out of each league page
  3. look for the team name in each tournament's team list
  4. read that tournament's division schedules and keep the team's games

To pin a specific league page instead, set LEAGUE_URLS below (or the
LEAGUE_URLS environment variable, comma-separated).

Past games already in the calendar are kept, so earlier seasons don't vanish
when a new season starts. Scores appear in the title once they're posted.

Needs: beautifulsoup4, lxml.
"""
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

TEAM_NAME = "We're Not Wrexham"
SHORT_NAME = "WNW"   # used in event titles
SOCCER_INDEX = "https://midstatesportsleagues.com/soccer/"
LEAGUE_URLS = []  # optional override, e.g. ["https://midstatesportsleagues.com/soccer/late-fall-wednesday-soccer/"]
TM = "https://tourneymachine.com/Public/Results/"
LOCAL_TZ = ZoneInfo("America/Chicago")
GAME_LENGTH = timedelta(minutes=50)
ALERT_BEFORE = None  # e.g. "PT1H" for a reminder 1 hour before each game
OUTPUT = os.environ.get("OUTPUT", "docs/were-not-wrexham.ics")
# Street addresses so the event location opens straight to directions.
# Matched by keyword anywhere in the league's venue name ("Maplewood HS - Field 2",
# "Maplewood High School, Field #2" both match "maplewood").
# Venues not listed here use the venue name alone (maps apps usually find it).
VENUE_ADDRESSES = {
    "boost": "Boost Fit Club, 11 Vaughns Gap Rd, Nashville, TN 37205",
    "maplewood": "Maplewood High School, 401 Walton Ln, Nashville, TN 37216",
    "stratford": "Stratford High School, 1800 Stratford Ave, Nashville, TN 37216",
}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def norm(name):
    """Compare names loosely: curly vs straight quotes, case, spacing, punctuation."""
    s = unicodedata.normalize("NFKD", unescape(name)).lower()
    return re.sub(r"[^a-z0-9]", "", s)


def league_pages():
    override = [u.strip() for u in os.environ.get("LEAGUE_URLS", "").split(",") if u.strip()]
    if override or LEAGUE_URLS:
        return override or LEAGUE_URLS
    html = fetch(SOCCER_INDEX)
    pages = sorted(set(re.findall(r"https://midstatesportsleagues\.com/soccer/[a-z0-9-]+/", html)))
    print(f"found {len(pages)} soccer league pages", file=sys.stderr)
    return pages


def tournament_ids(pages):
    ids = {}
    for page in pages:
        try:
            html = fetch(page)
        except Exception as e:
            print(f"warn: {page}: {e}", file=sys.stderr)
            continue
        for tid in re.findall(r"IDTournament=([A-Za-z0-9]+)", html):
            ids.setdefault(tid, page)
    return ids


def find_team(tid):
    """Return (team_ids, tournament_name, division_ids) if the team is in this tournament."""
    html = fetch(f"{TM}Tournament.aspx?IDTournament={tid}")
    soup = BeautifulSoup(html, "lxml")
    team_ids = set()
    target = norm(TEAM_NAME)
    for opt in soup.select("select option[value]"):
        label = re.sub(r"\s*\(Division:.*\)\s*$", "", opt.get_text())
        if opt["value"] and norm(label) == target:
            team_ids.add(opt["value"])
    if not team_ids:
        return None
    title = next((h.get_text(" ", strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)), "")
    divisions = sorted(set(re.findall(rf"IDTournament={tid}&(?:amp;)?IDDivision=([A-Za-z0-9]+)", html)))
    return team_ids, title, divisions


def cell_name(td):
    """Team cell holds the name, then a <br> and an (often empty) span."""
    for s in td.strings:
        if s.strip():
            return s.strip()
    return "TBD"


def standings(soup):
    """Map team id -> rank from the division standings table(s). Teams with no games yet get no rank."""
    ranks = {}
    for table in soup.select("table.tournamentResultsTable"):
        header = [th.get_text(strip=True) for th in table.find_all("th")]
        if not header or header[0] != "Team" or "W" not in header:
            continue
        rank = 0
        for tr in table.find_all("tr"):
            link = tr.find("a", href=re.compile(r"IDTeam="))
            if not link:
                continue
            rank += 1
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            played = sum(int(c) for c in cells[1:4] if c.isdigit())
            tid = re.search(r"IDTeam=([A-Za-z0-9]+)", link["href"]).group(1)
            if played:
                ranks[tid] = rank
    return ranks


def games_in_division(tid, did, team_ids, league_name, page):
    html = fetch(f"{TM}Division.aspx?IDTournament={tid}&IDDivision={did}")
    soup = BeautifulSoup(html, "lxml")
    ranks = standings(soup)
    heading = next((h.get_text(" ", strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)), "")
    games = []
    for tr in soup.select("tr.schedule_row"):
        classes = tr.get("class", [])
        if not any(f"team_{t}" in classes for t in team_ids):
            continue
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        date_div = tds[1].find(class_="schedule_row_date")
        date_txt = date_div.get_text(strip=True) if date_div else ""
        time_txt = tds[1].get_text(" ", strip=True).replace(date_txt, "").strip()
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2})", date_txt)
        if not m:
            continue
        try:
            when = datetime.strptime(f"{m.group(1)} {time_txt}", "%m/%d/%y %I:%M %p")
            timed = True
        except ValueError:  # time TBD: make it an all-day event
            when = datetime.strptime(m.group(1), "%m/%d/%y")
            timed = False
        t1, t2 = tds[3], tds[6]
        ours_first = t1.get("data-teamid") in team_ids
        opponent = cell_name(t2 if ours_first else t1)
        ours_td, opp_td = (t1, t2) if ours_first else (t2, t1)
        our_rank = ranks.get(ours_td.get("data-teamid"))
        opp_rank = ranks.get(opp_td.get("data-teamid"))
        s1, s2 = tds[4].get_text(strip=True), tds[5].get_text(strip=True)
        score = None
        if s1.isdigit() and s2.isdigit():
            score = (int(s1), int(s2)) if ours_first else (int(s2), int(s1))
        games.append({
            "id": tr.get("data-gameid") or f"{did}-{when:%Y%m%d%H%M}",
            "start": when.replace(tzinfo=LOCAL_TZ) if timed else when.date(),
            "timed": timed,
            "game_no": tds[0].get_text(strip=True),
            "location": tds[2].get_text(" ", strip=True),
            "opponent": opponent,
            "score": score,
            "our_rank": our_rank,
            "opp_rank": opp_rank,
            "division": heading,
            "league": league_name,
            "page": page,
        })
    return games


def esc(text):
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def fold(line):
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def venue_location(raw):
    """'Boost Fit Club - Field 3' -> street address (field number lives in the title)."""
    venue = re.sub(r"(?i)\s*[-,–]?\s*field\s*#?\s*\w+\s*$", "", raw).strip() or raw
    key = norm(venue)
    for word, address in VENUE_ADDRESSES.items():
        if norm(word) in key:
            return address
    return venue


def vevent(g, stamp):
    opp_title = re.sub(r"\s*\([^)]*\)\s*$", "", g["opponent"]) or g["opponent"]  # drop "(Red)" etc.
    field = re.search(r"(?i)field\s*#?\s*(\w+)", g["location"])
    field_txt = f" · Field {field.group(1)}" if field else ""
    if g.get("score"):
        us, them = g["score"]
        summary = f"⚽ {SHORT_NAME} {us}–{them} {opp_title}{field_txt}"
    else:
        # Upcoming games show current standings; finished games show the result instead.
        us = f"{SHORT_NAME} (#{g['our_rank']})" if g.get("our_rank") else SHORT_NAME
        them = f"{opp_title} (#{g['opp_rank']})" if g.get("opp_rank") else opp_title
        summary = f"⚽ {us} vs {them}{field_txt}"
    desc = [f"Opponent: {g['opponent']}", f"Where: {g['location']}"]
    if g["league"]:
        desc.append(f"{g['league']} · {g['division']}".strip(" ·"))
    if g["game_no"]:
        desc.append(f"Game {g['game_no']}")
    if not g["timed"]:
        desc.append("Game time not posted yet")
    desc.append(f"Schedule: {g['page']}")
    lines = ["BEGIN:VEVENT", f"UID:tm-{g['id']}@were-not-wrexham-ics", f"DTSTAMP:{stamp}"]
    if g["timed"]:
        lines += [f"DTSTART:{utc(g['start'])}", f"DTEND:{utc(g['start'] + GAME_LENGTH)}"]
    else:
        d = g["start"]
        lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
    lines += [
        f"SUMMARY:{esc(summary)}",
        f"LOCATION:{esc(venue_location(g['location']))}",
        f"DESCRIPTION:{esc(chr(10).join(desc))}",
    ]
    if ALERT_BEFORE and g["timed"]:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(summary)}",
                  f"TRIGGER:-{ALERT_BEFORE}", "END:VALARM"]
    lines.append("END:VEVENT")
    return "\r\n".join(fold(l) for l in lines)


def past_events_from_existing(keep_out_uids):
    """Keep already-played games from the current file so old seasons stay in the calendar."""
    if not os.path.exists(OUTPUT):
        return []
    text = open(OUTPUT, encoding="utf-8").read().replace("\r\n ", "")
    kept, now = [], datetime.now(timezone.utc)
    for block in re.findall(r"BEGIN:VEVENT\r?\n.*?END:VEVENT", text, re.S):
        uid = re.search(r"^UID:(.*)$", block, re.M)
        start = re.search(r"^DTSTART(?:;VALUE=DATE)?:(\d{8})(T\d{6}Z)?", block, re.M)
        if not uid or not start or uid.group(1).strip() in keep_out_uids:
            continue
        d = datetime.strptime(start.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
        if d < now - timedelta(days=1):
            kept.append((d, "\r\n".join(fold(l) for l in block.splitlines())))
    return kept


def main():
    games = []
    for tid, page in tournament_ids(league_pages()).items():
        try:
            found = find_team(tid)
        except Exception as e:
            print(f"warn: tournament {tid}: {e}", file=sys.stderr)
            continue
        if not found:
            continue
        team_ids, league_name, divisions = found
        print(f"team found in {league_name or tid} ({page})", file=sys.stderr)
        for did in divisions:
            try:
                games += games_in_division(tid, did, team_ids, league_name, page)
            except Exception as e:
                print(f"warn: division {did}: {e}", file=sys.stderr)

    if not games:
        # Between seasons, or the site is down: leave the current calendar alone.
        print(f"no games found for {TEAM_NAME}; keeping existing calendar", file=sys.stderr)
        return

    seen, unique = set(), []
    for g in games:
        if g["id"] not in seen:
            seen.add(g["id"])
            unique.append(g)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    new_uids = {f"tm-{g['id']}@were-not-wrexham-ics" for g in unique}
    events = past_events_from_existing(new_uids)
    for g in unique:
        key = g["start"] if g["timed"] else datetime.combine(g["start"], datetime.min.time(), LOCAL_TZ)
        events.append((key.astimezone(timezone.utc), vevent(g, stamp)))
    events.sort(key=lambda x: x[0])

    head = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//were-not-wrexham-ics//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(TEAM_NAME)} ⚽",
        "X-WR-CALDESC:Mid State Sports Leagues rec soccer games (auto-updated)",
        "X-WR-TIMEZONE:America/Chicago",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
    ]
    body = "\r\n".join(fold(l) for l in head) + "\r\n"
    body += "".join(e + "\r\n" for _, e in events) + "END:VCALENDAR\r\n"
    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    print(f"wrote {len(unique)} upcoming/current games (+{len(events) - len(unique)} past) to {OUTPUT}")


if __name__ == "__main__":
    main()
