#!/usr/bin/env python3
"""Render real GitHub contributions as self-hosted desktop and mobile SVGs.

Only Python's standard library is needed. If GitHub changes its markup, returns
an incomplete calendar, or cannot be reached, fail before replacing the assets.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import urllib.request


SOURCE = "https://github.com/users/CPBzhan/contributions"
COLORS = ("#17232d", "#204b42", "#28765d", "#3ab78b", "#6ef3c5")
MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Day:
    date: date
    level: int
    count: int


@dataclass(frozen=True)
class Calendar:
    days: tuple[Day, ...]
    reported_total: int | None


class ContributionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells = {}
        self.tooltips = {}
        self.start = None
        self.end = None
        self.tooltip_id = None
        self.tooltip_text = []
        self.in_heading = False
        self.heading = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-from" in attrs and "data-to" in attrs:
            self.start = date.fromisoformat(attrs["data-from"][:10])
            self.end = date.fromisoformat(attrs["data-to"][:10])
        if "data-date" in attrs:
            cell_id = attrs.get("id")
            if not cell_id or cell_id in self.cells or "data-level" not in attrs:
                raise ValueError("Contribution cell has a missing or duplicate identity/level")
            self.cells[cell_id] = (date.fromisoformat(attrs["data-date"]), int(attrs["data-level"]))
        if tag == "tool-tip" and attrs.get("for"):
            self.tooltip_id = attrs["for"]
            self.tooltip_text = []
        if tag == "h2" and attrs.get("id") == "js-contribution-activity-description":
            self.in_heading = True

    def handle_data(self, data):
        if self.tooltip_id:
            self.tooltip_text.append(data)
        if self.in_heading:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == "tool-tip" and self.tooltip_id:
            self.tooltips[self.tooltip_id] = " ".join("".join(self.tooltip_text).split())
            self.tooltip_id = None
        if tag == "h2":
            self.in_heading = False


def parse_contributions(html: str) -> Calendar:
    parser = ContributionParser()
    parser.feed(html)
    parser.close()
    if not parser.cells or parser.start is None or parser.end is None:
        raise ValueError("GitHub did not return a dated contribution calendar")
    expected_days = (parser.end - parser.start).days + 1
    if not 1 <= expected_days <= 371:
        raise ValueError("Contribution calendar has an unexpected date range")

    days = []
    seen = set()
    for cell_id, (day, level) in parser.cells.items():
        if day in seen or not 0 <= level <= 4:
            raise ValueError("Contribution calendar has a duplicate date or invalid level")
        seen.add(day)
        tooltip = parser.tooltips.get(cell_id, "")
        match = re.match(r"^(No|[\d,]+) contributions? on\b", tooltip)
        if not match:
            raise ValueError(f"Missing contribution count for {day}")
        count = 0 if match[1] == "No" else int(match[1].replace(",", ""))
        if (count == 0) != (level == 0):
            raise ValueError(f"Contribution count and intensity disagree for {day}")
        days.append(Day(day, level, count))

    expected = {parser.start + timedelta(days=offset) for offset in range(expected_days)}
    if seen != expected:
        raise ValueError("GitHub returned an incomplete contribution calendar")
    days.sort(key=lambda item: item.date)
    heading = " ".join("".join(parser.heading).split())
    total = re.match(r"^([\d,]+) contributions?\b", heading)
    return Calendar(tuple(days), int(total[1].replace(",", "")) if total else None)


def short_date(day: date) -> str:
    return f"{MONTHS[day.month]} {day.day:02d}, {day.year}"


def render_svg(calendar: Calendar, snapshot: date, *, mobile: bool = False) -> str:
    end = calendar.days[-1].date
    final_sunday = end - timedelta(days=(end.weekday() + 1) % 7)
    cutoff = final_sunday - timedelta(weeks=25)
    days = tuple(day for day in calendar.days if not mobile or day.date >= cutoff)
    start = days[0].date
    first_sunday = start - timedelta(days=(start.weekday() + 1) % 7)
    columns = (end - first_sunday).days // 7 + 1
    total = sum(day.count for day in days)
    width, height = (600, 385) if mobile else (1000, 245)
    grid_x, grid_y, step, size = (80, 135, 18, 14) if mobile else (76, 90, 16, 12)
    title_size, body_size = (30, 24) if mobile else (22, 13)
    month_y, month_size = (119, 22) if mobile else (78, 11)
    coverage = f"{short_date(start)} – {short_date(end)}"
    window = f"{columns} weeks shown" if mobile else f"{len(days)} days shown"
    description = (f"CPBzhan's GitHub contribution calendar. {total} contributions across "
                   f"{coverage}. Snapshot retrieved {snapshot.isoformat()} UTC. "
                   "Each square uses GitHub's original intensity level; individual titles give exact counts. "
                   f"Source: {SOURCE}")
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="activity-title activity-desc">',
        '  <title id="activity-title">CPBzhan · Contribution activity</title>',
        f'  <desc id="activity-desc">{escape(description)}</desc>',
        '  <style>',
        '    text { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; }',
        '    .mono { font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; }',
        '    .accent { animation: accent-pulse 6s ease-in-out infinite; }',
        '    @keyframes accent-pulse { 0%, 100% { opacity: .4; } 50% { opacity: 1; } }',
        '    @media (prefers-reduced-motion: reduce) { .accent { animation: none; } }',
        '  </style>',
        f'  <rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="18" fill="#080d14" stroke="#22313d"/>',
        f'  <rect x="1" y="1" width="{width - 2}" height="{100 if mobile else 65}" rx="17" fill="#0e1721"/>',
        f'  <path d="M24 1 H{180 if mobile else 220}" stroke="#6ef3c5" stroke-width="2" class="accent"/>',
        f'  <text x="{24 if mobile else 30}" y="{45 if mobile else 36}" fill="#e4edf3" font-size="{title_size}" font-weight="600">Contribution activity</text>',
    ]
    if mobile:
        svg.append(f'  <text x="24" y="82" fill="#6ef3c5" font-size="{body_size}">{total:,} contributions · {window}</text>')
    else:
        svg.extend([
            '  <text x="30" y="55" fill="#8a9ba8" font-size="11" class="mono">CPBZHAN / GITHUB HISTORY</text>',
            f'  <text x="970" y="36" text-anchor="end" fill="#6ef3c5" font-size="{body_size}">{total:,} contributions shown</text>',
            f'  <text x="970" y="55" text-anchor="end" fill="#8a9ba8" font-size="11">{window}</text>',
        ])

    # Month labels follow actual week columns; only the accent border animates.
    last_month = None
    for column in range(columns):
        sunday = first_sunday + timedelta(weeks=column)
        representative = max(sunday, start)
        if representative.month != last_month:
            # Avoid a clipped label at the right edge of a partial final week.
            if column < columns - 2:
                svg.append(f'  <text x="{grid_x + column * step}" y="{month_y}" fill="#8a9ba8" font-size="{month_size}">{MONTHS[representative.month]}</text>')
            last_month = representative.month
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        svg.append(f'  <text x="{24 if mobile else 30}" y="{grid_y + row * step + size - 1}" fill="#8a9ba8" font-size="{20 if mobile else 10}">{label}</text>')
    for day in days:
        column, row = divmod((day.date - first_sunday).days, 7)
        label = f"{day.date.isoformat()}: {day.count} contribution{'s' if day.count != 1 else ''}"
        svg.append(f'  <rect x="{grid_x + column * step}" y="{grid_y + row * step}" width="{size}" height="{size}" rx="3" fill="{COLORS[day.level]}" data-date="{day.date.isoformat()}" data-count="{day.count}" data-level="{day.level}"><title>{label}</title></rect>')

    if mobile:
        svg.extend([
            f'  <text x="24" y="293" fill="#8a9ba8" font-size="22">{escape(coverage)}</text>',
            f'  <text x="24" y="325" fill="#8a9ba8" font-size="22">Snapshot · {snapshot.isoformat()} UTC</text>',
        ])
        legend_x, legend_y, legend_size, legend_step, legend_font = 82, 347, 16, 24, 22
        svg.append('  <text x="24" y="361" fill="#8a9ba8" font-size="22">Less</text>')
    else:
        svg.extend([
            f'  <text x="30" y="225" fill="#8a9ba8" font-size="11">{escape(coverage)}</text>',
            f'  <text x="350" y="225" fill="#8a9ba8" font-size="11">Snapshot · {snapshot.isoformat()} UTC</text>',
            '  <text x="808" y="225" fill="#8a9ba8" font-size="10">Less</text>',
        ])
        legend_x, legend_y, legend_size, legend_step, legend_font = 840, 215, 11, 17, 10
    for level, color in enumerate(COLORS):
        svg.append(f'  <rect x="{legend_x + level * legend_step}" y="{legend_y}" width="{legend_size}" height="{legend_size}" rx="3" fill="{color}"><title>GitHub intensity level {level} of 4</title></rect>')
    svg.append(f'  <text x="{legend_x + 5 * legend_step + 3}" y="{legend_y + legend_size - 1}" fill="#8a9ba8" font-size="{legend_font}">More</text>')
    svg.append('</svg>')
    return "\n".join(svg) + "\n"


def update_activity(html: str, output: Path, snapshot: date) -> Calendar:
    calendar = parse_contributions(html)
    age = (snapshot - calendar.days[-1].date).days
    if not 0 <= age <= 2:
        raise ValueError("Contribution calendar is stale or dated in the future")
    assets = {
        output: render_svg(calendar, snapshot),
        output.with_name("activity-mobile.svg"): render_svg(calendar, snapshot, mobile=True),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    for target, svg in assets.items():
        # Validation and rendering finish before either existing asset is touched.
        temporary = target.with_suffix(".svg.tmp")
        try:
            temporary.write_text(svg, encoding="utf-8", newline="\n")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return calendar


def main() -> int:
    output = Path(__file__).resolve().parents[1] / "assets" / "activity.svg"
    request = urllib.request.Request(SOURCE, headers={
        "User-Agent": "CPBzhan-profile-activity/1.0",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read(2_000_001)
        if len(html) > 2_000_000:
            raise ValueError("Contribution response exceeds the expected size")
        snapshot = datetime.now(timezone.utc).date()
        calendar = update_activity(html.decode("utf-8"), output, snapshot)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Contribution refresh failed; existing assets preserved: {error}", file=sys.stderr)
        return 1
    print(f"Saved desktop and mobile snapshots: {len(calendar.days)} days, "
          f"{sum(day.count for day in calendar.days)} contributions; "
          f"{calendar.days[0].date} through {calendar.days[-1].date}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
