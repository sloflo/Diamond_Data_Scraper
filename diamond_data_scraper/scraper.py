from __future__ import annotations

import logging
import re
from collections import defaultdict
from time import sleep
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from selenium.webdriver.common.by import By

from .constants import (
    STAT_TABLE_KEY_RE,
    YEAR_LEAGUE_HEADER_RE,
    YEARLY_LINK_RE,
)
from .webdriver_factory import build_chrome_driver


class Scraper:
    """
    Scrapes yearly baseball league stats from Baseball Almanac.

    High-level flow:
    - Collect yearly links (AL/NL).
    - For each year page, parse player/team tables and a small "events" blurb.
    - Flatten into Pandas DataFrames and export to CSV.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        profile_dir: str = "selenium_profile",
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the scraper state and create a Selenium Chrome driver.

        - **headless**: Run Chrome without a visible UI.
        - **profile_dir**: Directory where Chrome user-data is stored (cache/cookies).
        - **logger**: Optional logger for progress reporting.
        """
        self.logger = logger or logging.getLogger(__name__)

        self.events: Dict[int, Dict[str, List[str]]] = {}
        self.player_stats: DefaultDict[int, Dict[str, Dict[str, List[Dict[str, str]]]]] = defaultdict(dict)
        self.team_stats: DefaultDict[int, Dict[str, Dict[str, List[Dict[str, str]]]]] = defaultdict(dict)

        self.logger.info("Initializing Chrome driver (headless=%s, profile_dir=%s)", headless, profile_dir)
        self.driver = build_chrome_driver(headless=headless, profile_dir=profile_dir)
        self.logger.info("Chrome driver ready")

    def close(self) -> None:
        """Close the Selenium driver (safe to call multiple times)."""
        try:
            self.logger.info("Closing Chrome driver")
            self.driver.quit()
        except Exception:
            pass

    # ---------- Orchestration ----------
    def scrape(
        self,
        *,
        menu_url: str,
        limit_years: Optional[int] = None,
        out_dir: str = ".",
        league: str = "BOTH",
    ) -> None:
        """
        Orchestrate the end-to-end scrape and write CSV outputs.

        - **menu_url**: Year-menu URL to start from.
        - **limit_years**: If provided, only scrape the first N yearly links.
        - **out_dir**: Directory where CSVs are written.
        - **league**: Which league to scrape: 'AL', 'NL', or 'BOTH' (default).
        """
        try:
            self.logger.info("Scrape started")
            links = self.get_year_links(menu_url, league=league)

            if limit_years is not None:
                if limit_years <= 0:
                    self.logger.warning("limit_years=%s requested; nothing to scrape", limit_years)
                    return
                self.logger.info("Limiting scrape to first %d yearly links (testing mode)", limit_years)
                links = links[:limit_years]

            self.log_data(links)
        finally:
            self.close()

        self.logger.info("Converting scraped stats to DataFrames")
        player_hit_df, player_pitch_df, _player_standing_df = self.convert_stats_to_df(self.player_stats)
        team_hit_df, team_pitch_df, standing_df = self.convert_stats_to_df(self.team_stats)

        outputs = [
            ("player_hit.csv", player_hit_df),
            ("player_pitch.csv", player_pitch_df),
            ("team_hit.csv", team_hit_df),
            ("team_pitch.csv", team_pitch_df),
            ("standing.csv", standing_df),
        ]

        for filename, df in outputs:
            path = f"{out_dir.rstrip('/')}/{filename}"
            self.logger.info("Writing %s (%d rows, %d cols)", path, len(df.index), len(df.columns))
            df.to_csv(path, index=False)

        self.logger.info("Scrape finished successfully")

    # ---------- Navigation ----------
    def get_year_links(self, menu_url: str, *, league: str = "BOTH") -> List[str]:
        """
        Load the year-menu page and return yearly AL/NL links.

        Filter:
        - keep all National League years
        - keep American League only for years >= 1901

        league:
        - 'AL': only American League
        - 'NL': only National League
        - 'BOTH': both leagues
        """
        self.logger.info("Loading year menu: %s", menu_url)
        self.driver.get(menu_url)

        anchors = self.driver.find_elements(
            By.CSS_SELECTOR,
            "table.ba-sub > tbody > tr > td.datacolBox > a",
        )

        want: Optional[str] = None
        if league == "AL":
            want = "a"
        elif league == "NL":
            want = "n"

        links: List[str] = []
        for a in anchors:
            href = a.get_attribute("href") or ""
            m = YEARLY_LINK_RE.search(href)
            if not m:
                continue

            year = int(m.group("year"))
            league_code = m.group("league_code")

            if want is not None and league_code != want:
                continue

            if league_code == "a" and year < 1901:
                continue

            links.append(href)

        self.logger.info("Found %d yearly links (post-filter)", len(links))
        return links

    def log_data(self, links: Iterable[str]) -> None:
        """
        Visit each yearly link and extract player/team/event data into in-memory dictionaries.
        """
        links_list = list(links)
        total = len(links_list)
        self.logger.info("Scraping %d yearly pages", total)

        for idx, link in enumerate(links_list, start=1):
            try:
                self.logger.info("(%d/%d) Loading: %s", idx, total, link)
                self.driver.get(link)
                sleep(2)
            except Exception:
                self.logger.warning("(%d/%d) Failed to load: %s", idx, total, link)
                continue

            year, league = self.get_year_league()
            if not year or not league:
                self.logger.warning("(%d/%d) Skipping page (could not parse year/league): %s", idx, total, link)
                continue

            self.logger.info("(%d/%d) Parsed: year=%s league=%s", idx, total, year, league)
            player, team = self.get_data()
            self.player_stats[year][league] = player
            self.team_stats[year][league] = team

            self.logger.info(
                "(%d/%d) Extracted tables: player=%d team=%d",
                idx,
                total,
                len(player.keys()),
                len(team.keys()),
            )

            if year not in self.events:
                self.events[year] = self.clean_events()
                self.logger.info("(%d/%d) Extracted events keys: %s", idx, total, list(self.events[year].keys()))

    def get_year_league(self) -> Tuple[Optional[int], Optional[str]]:
        """
        Parse the current yearly page header to determine (year, league).

        Returns `(None, None)` when the header doesn't match expectations.
        """
        try:
            header = self.driver.find_element(By.CSS_SELECTOR, "div.intro > h1").text
        except Exception:
            return None, None

        m = YEAR_LEAGUE_HEADER_RE.search(header or "")
        if not m:
            return None, None

        year = int(m.group("year"))
        league = m.group("league").title() + " League"

        if league == "American League" and year < 1901:
            return None, None

        return year, league

    # ---------- Page parsing ----------
    def get_data(self) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, List[Dict[str, str]]]]:
        """
        Parse all boxed tables on the current yearly page.

        Returns:
        - `player_stats_dict`: maps stat table name -> list of row dicts
        - `team_stats_dict`: maps stat table name -> list of row dicts
        """
        player_stats_dict: Dict[str, List[Dict[str, str]]] = {}
        team_stats_dict: Dict[str, List[Dict[str, str]]] = {}

        boxed_tables = self.driver.find_elements(By.CSS_SELECTOR, "table.boxed")
        self.logger.debug("Found %d boxed tables on page", len(boxed_tables))

        for table in boxed_tables:
            col_names: List[str] = []
            duplicate_rows: Dict[int, List[Any]] = {}
            table_name: Optional[List[str]] = None
            col_num: Optional[int] = None
            data_list: List[List[str]] = []

            rows = table.find_elements(By.TAG_NAME, "tr")
            for row in rows:
                temp_table_name, temp_col_num = self.find_table_name_and_columns(row)
                temp_col_names, temp_dup_from_header = self.find_col_names(row)
                row_data, temp_dup_from_cells = self.find_cell_data(row, col_num, duplicate_rows)

                if temp_table_name:
                    table_name = temp_table_name
                if temp_col_num:
                    col_num = temp_col_num
                if temp_dup_from_header:
                    duplicate_rows = temp_dup_from_header
                if temp_col_names:
                    col_names = temp_col_names
                if temp_dup_from_cells is not None:
                    duplicate_rows = temp_dup_from_cells

                if row_data and col_names and len(row_data) == len(col_names):
                    data_list.append(row_data)

            if table_name and col_names and data_list:
                list_of_dicts = [dict(zip(col_names, row)) for row in data_list]
                if table_name[0] == "Player":
                    player_stats_dict[table_name[-1]] = list_of_dicts
                elif table_name[0] == "Team":
                    team_stats_dict[table_name[-1]] = list_of_dicts

                self.logger.debug(
                    "Captured table %s (%d rows, %d cols)",
                    " / ".join(table_name),
                    len(list_of_dicts),
                    len(col_names),
                )

        return player_stats_dict, team_stats_dict

    def find_table_name_and_columns(self, row) -> Tuple[Optional[List[str]], Optional[int]]:
        """
        Detect the table category/name from header rows and extract expected column count.

        Returns:
        - `(table_name_parts, num_cols)` where `table_name_parts` looks like
          `["Player", "Hitting Statistics"]` or `["Team", "Standings"]`
        - `(None, None)` when the row isn't a header row
        """
        table_name: List[str] = []
        player_pattern = r"(Player|Pitcher)"
        team_pattern = r"Team(?= Review)|Team Standings"

        headers: List[str] = []
        try:
            headers = [h.text for h in row.find_elements(By.XPATH, ".//h2 | .//p")]
        except Exception:
            return None, None

        if not headers:
            return None, None

        try:
            num_cols_attr = row.find_element(By.TAG_NAME, "td").get_attribute("colspan")
            num_cols = int(num_cols_attr) if num_cols_attr else None
        except Exception:
            num_cols = None

        # Player/Pitcher tables are treated as "Player" category.
        is_player = bool(headers and headers[0] and re.search(player_pattern, headers[0]))
        if is_player:
            table_name.append("Player")

        # Team tables can show up in different header positions depending on the page.
        header0 = headers[0] if len(headers) > 0 else ""
        header1 = headers[1] if len(headers) > 1 else ""
        m_team = re.search(team_pattern, header0) or re.search(team_pattern, header1)
        if m_team:
            table_name.extend(m_team.group().split(" "))

        # Stat key is usually in the second header line (but we normalize it).
        if len(headers) > 1:
            m_key = STAT_TABLE_KEY_RE.search(headers[1])
            if m_key:
                table_name.append(m_key.group(1))

        if not table_name:
            return None, None

        return table_name, num_cols

    def find_col_names(self, row) -> Tuple[Optional[List[str]], Optional[Dict[int, List[Any]]]]:
        """
        Extract column names from a "banner" row and detect header rowspans.
        """
        try:
            elements = row.find_elements(By.XPATH, ".//td[contains(@class, 'banner')]")
        except Exception:
            return None, None

        if not elements:
            return None, None

        col_names: List[str] = []
        duplicate_row_val: Dict[int, List[Any]] = {}
        regions = {"East", "Central", "West"}

        for idx, el in enumerate(elements):
            num_rows = el.get_attribute("rowspan")
            if num_rows:
                duplicate_row_val[idx] = [el.text, int(num_rows)]

            if el.text in regions:
                col_names.append("Region")
            else:
                col_names.append(el.text.replace(" [Click for roster]", "").strip())

        return col_names, duplicate_row_val

    def find_cell_data(
        self,
        row,
        num_cols: Optional[int],
        duplicate_rows: Dict[int, List[Any]],
    ) -> Tuple[Optional[List[str]], Dict[int, List[Any]]]:
        """
        Extract cell text for a data row, handling rowspans by re-inserting duplicated values.
        """
        try:
            cells = row.find_elements(
                By.XPATH,
                ".//td[contains(@class, 'datacolBox') or contains(@class, 'datacolBlue')]",
            )
        except Exception:
            return None, duplicate_rows

        if not cells:
            return None, duplicate_rows

        data: List[str] = []
        for idx, cell in enumerate(cells):
            num_rows = cell.get_attribute("rowspan")
            if num_rows:
                duplicate_rows[idx] = [cell.text, int(num_rows)]
            data.append(cell.text.strip())

        if num_cols is not None and len(data) != num_cols:
            for idx, value in list(duplicate_rows.items()):
                data.insert(idx, value[0])
                duplicate_rows[idx][1] -= 1

        duplicate_rows = {k: v for k, v in duplicate_rows.items() if v[1] > 0}
        return data, duplicate_rows

    def clean_events(self) -> Dict[str, List[str]]:
        """
        Extract the small "Events" / "Salary" text block from the current yearly page.
        """
        events_dict: Dict[str, List[str]] = {}
        try:
            row = self.driver.find_element(By.XPATH, ".//td[contains(., 'Events') or contains(., 'Salary')]")
        except Exception:
            return events_dict

        event_text = (row.text or "").split("\n")
        for line in event_text:
            if ": " not in line:
                continue

            title, rhs = line.split(": ", 1)
            if "Events" in title or "Salary" in title:
                events_dict[title] = rhs.split(" | ")

        return events_dict

    # ---------- DataFrame/output helpers ----------
    def convert_stats_to_df(
        self,
        dictionary: Dict[int, Dict[str, Dict[str, List[Dict[str, str]]]]],
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Flatten the nested stats dictionary into three DataFrames:
        - hitting stats
        - pitching stats
        - standings
        """
        hit_table: List[Dict[str, Any]] = []
        pitch_table: List[Dict[str, Any]] = []
        standing_table: List[Dict[str, Any]] = []

        for year, leagues in dictionary.items():
            for league, data in leagues.items():
                for items in data.get("Hitting Statistics", []):
                    self.add_to_table(hit_table, items, year, league)
                for items in data.get("Pitching Statistics", []):
                    self.add_to_table(pitch_table, items, year, league)
                for items in data.get("Standings", []):
                    self.add_to_table(standing_table, self.normalize_standings_row(items), year, league)

        standing_df = pd.DataFrame(standing_table)
        standing_df = self.reorder_standing_columns(standing_df)

        return pd.DataFrame(hit_table), pd.DataFrame(pitch_table), standing_df

    def normalize_standings_row(self, items: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize known Baseball Almanac standings header variants to a canonical schema.

        Some years use headers like:
          - "Team [Click for roster]" instead of "Team | Roster"
          - "Wins"/"Losses" instead of "W"/"L"

        We normalize to:
          Team, Roster, W, L, WP, GB, ...
        """
        if not items:
            return items

        out = dict(items)

        # Team header variants
        if "Team [Click for roster]" in out and "Team" not in out:
            out["Team"] = out.pop("Team [Click for roster]")

        # Older layouts sometimes use a combined "Team | Roster" header.
        # We treat this as "Team" and add an empty "Roster" column to keep schema consistent.
        if "Team | Roster" in out:
            value = out.pop("Team | Roster")
            # Only overwrite Team if it doesn't already exist.
            out.setdefault("Team", value)
            out.setdefault("Roster", "")

        # W/L header variants
        if "Wins" in out and "W" not in out:
            out["W"] = out.pop("Wins")
        if "Losses" in out and "L" not in out:
            out["L"] = out.pop("Losses")

        return out

    def reorder_standing_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Enforce a consistent column order for standings and drop unused variants.

        Target order (when present):
          Team, W, L, WP, GB, T, Year, League
        Any additional columns are appended after this sequence.
        The "Roster" column is dropped (it's empty after normalization).
        """
        if df.empty:
            return df

        desired_order = ["Team", "W", "L", "WP", "GB", "T", "Year", "League"]

        # Drop Roster if it exists; the user doesn't want it in the output.
        if "Roster" in df.columns:
            df = df.drop(columns=["Roster"])

        ordered_cols = [c for c in desired_order if c in df.columns]
        remaining_cols = [c for c in df.columns if c not in ordered_cols]

        return df[ordered_cols + remaining_cols]

    def add_to_table(self, table: List[Dict[str, Any]], items: Dict[str, Any], year: int, league: str) -> None:
        """Append a single stats row into an output table, adding Year/League context columns."""
        if not items:
            return

        stats = dict(items)
        stats["Year"] = year
        stats["League"] = league
        table.append(stats)

    def convert_events_to_df(self, dictionary: Dict[int, Dict[str, List[str]]]) -> pd.DataFrame:
        """Convert the events dictionary into a DataFrame for easier export/analysis."""
        rows: List[Dict[str, Any]] = []
        for year, event_groups in dictionary.items():
            for title, items in event_groups.items():
                rows.append({"Year": year, "Title": title, "Items": " | ".join(items)})
        return pd.DataFrame(rows)

