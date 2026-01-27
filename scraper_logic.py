import os
import pandas as pd
import json
from time import sleep
import re
from collections import defaultdict

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

# Define a directory for the user profile (cache and cookies will be saved here)
profile_dir = os.path.abspath('selenium_profile')

# Ensure the directory exists
if not os.path.exists(profile_dir):
    os.makedirs(profile_dir)

options = webdriver.ChromeOptions()
options.add_argument('--headless')  # Enable headless mode
options.add_argument('--disable-gpu')  # Optional, recommended for Windows
options.add_argument(f"--user-data-dir={profile_dir}") # Specify the user data directory argument

driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()),options=options)

class Scraper():
    def __init__(self):
        self.events = {}
        self.player_stats = defaultdict(dict)
        self.team_stats = defaultdict(dict)
        self.scrape()

    def scrape(self):
        try:
            links_to_scrape = self.get_year_links("https://www.baseball-almanac.com/yearmenu.shtml")
            links = ["https://www.baseball-almanac.com/yearly/yr1996n.shtml"]
            self.log_data(links)
            
        except Exception as e:
            print("Unable to open the url provided.")
            print(f"Exception: {type(e).__name__} {e}")

        player_hit_df, player_pitch_df, standing_df = self.convert_stats_to_df(self.player_stats)
        team_hit_df, team_pitch_df, standing_df = self.convert_stats_to_df(self.team_stats)
        
        # # TODO THIS IS TEST TO MAKE SURE DATA IS CORRECT
        # temp = pd.json_normalize(self.player_stats)
        # temp.to_csv("test.csv", index = False)
        print(player_hit_df)
        
        driver.quit()
  
    def get_year_links(self, link):
        driver.get(link)
        search_results = driver.find_elements(By.CSS_SELECTOR, "table.ba-sub > tbody > tr > td.datacolBox > a")
        # only scraping data for the American and National leagues
        pattern = r"yr\d{4}(a|n)\.shtml$"
        links = [link.get_attribute("href") for link in search_results if re.search(pattern, link.get_attribute("href"))]
    
        return links
    
    # This gets the driver for the new page
    def get_driver_new_page(self, link):
        driver.get(link)
    
    def get_year_league(self, driver):
        # pulling the header from the intro to get the year and the league
        scraped_data = driver.find_element(By.CSS_SELECTOR, "div.intro > h1")
        pattern = r"\d{4}\s(AMERICAN|NATIONAL)\sLEAGUE"
        try:
            search_result = re.search(pattern, scraped_data.text).group()
            if search_result:
                year, league = search_result.split(" ", 1)
                return int(year), league.title()
        # TODO This is being raised because American Association has link that also ends in a.  Need to fix
        except Exception:
            return None, None

        
    # TODO Make this smaller functions T_T
    def get_data(self, driver):
        player_stats_dict = {}
        team_stats_dict = {}
        key_list = []
        search_results = driver.find_elements(By.CSS_SELECTOR, "table.boxed")
        
        for result in search_results:
            banners = []
            cell_results = []
            rows = result.find_elements(By.TAG_NAME, "tr")
            keys = []
            
            prev_cells = None
            for row in rows:
                # league_pattern = r"(American|National)\sLeague"
                player_pattern = r"(Player|Pitcher)"
                team_pattern = r"Team(?= Review)|Team Standings"
                stat_name = r"^.+Statistics"
                headers = [header.text for header in row.find_elements(By.XPATH, ".//h2 | .//p")]
                if headers:
                    if match := re.search(player_pattern, headers[0]):
                        player = "Player"
                        keys.append(player)
                    if match := re.search(team_pattern, headers[0]) or (match := re.search(team_pattern, headers[1])):
                        team = match.group().split(" ")
                        keys.extend(team)
                    if match := re.search(stat_name, headers[1]):
                        stat = match.group()
                        keys.append(stat)
                banners = [banner.text.replace(" [Click for roster]", "") for banner in row.find_elements(By.XPATH, ".//td[contains(@class, 'banner')]")]
                if banners:
                    key_list = [key for key in banners if key != "Top 25"]
                cells = [stat.text.strip() for stat in row.find_elements(By.XPATH, ".//td[contains(@class, 'datacolBox') or contains(@class, 'datacolBlue')]") if stat.text != "Top 25"]
                if cells:
                    regions = ["East", "Central", "West"]
                    if "Standings" in keys:
                        if key_list[0] in regions:
                            region = key_list[0]
                            key_list[0] = "Region"
                        cells.insert(0, region)
                    if len(cells) != len(key_list):
                        cells.insert(0, prev_cells[0])
                        diff = len(prev_cells) - len(cells)
                        cells.extend(prev_cells[-diff:])
                    if len(cells) > 1:
                        prev_cells = cells
                        cell_results.append(cells)
            # TODO clean up events (do it in a seperate function??)
                
            list_of_dictionaries = [dict(zip(key_list, values)) for values in cell_results]
            if keys[0] == "Player":
                player_stats_dict[keys[1]] = list_of_dictionaries
            elif keys[0] == "Team":
                team_stats_dict[keys[1]] = list_of_dictionaries
        return player_stats_dict, team_stats_dict
        
    def clean_events(self, driver):
        # TODO save events links and scrape that for winners
        events_dict = {}
        row = driver.find_element(By.XPATH, ".//td[contains(text(), 'Events') or contains(text(), 'Salary')]")
        event_text = row.text.split("\n")
        
        for text in event_text:
            text = text.split(": ")
            title = text[0]
            info = text[1].split(" | ")
            if "Events" in title or "Salary" in title:
                events_dict[title] = info
        return events_dict
        
    def get_event(self, driver):
        search_results = driver.find_elements(By.CSS_SELECTOR, "table.boxed > tbody > tr")
        
        print(search_results)
    
    def log_data(self, links : list):
        for link in links:
            try:
                driver.get(link)
                year, league = self.get_year_league(driver)
            # TODO Currently exception is happening because American Association link also ends in a.  Need to figure out how to remove those from link list
            except Exception:
                break
            
            if year and league:
                player, team = self.get_data(driver)
                self.player_stats[year][league] = player
                self.team_stats[year][league] = team
                
                if not self.events.get(year):
                    events = self.clean_events(driver)
                    self.events[year] = events
    
    def convert_events_to_df(self, dictionary):
        # Events will have tables [Events, Salary]
        events_list = ["Special Events", "Salary"]
    
    def convert_stats_to_df(self, dictionary):
        hit_table = []
        pitch_table = []
        standing_table = []
        # Current list of tables for stats [Hitting Statistics, Pitching Statistics, Standings]
        for year, leagues in dictionary.items():
            for league, data in leagues.items():
                for items in data.get("Hitting Statistics", []):
                    self.add_to_table(hit_table, items, year, league)
                for items in data.get("Pitching Statistics", []):
                    self.add_to_table(pitch_table, items, year, league)
                for items in data.get("Standings", []):
                    self.add_to_table(standing_table, items, year, league)
                    
        hit_stats = pd.DataFrame(hit_table)
        pitch_stats = pd.DataFrame(pitch_table)
        standing_stats = pd.DataFrame(standing_table)
        
        return hit_stats, pitch_stats, standing_stats
        

    def add_to_table(self, table, items, year, league):
        if items:
            stats = items.copy()
            stats["Year"] = year
            stats["League"] = league
            table.append(stats)

if __name__ == "__main__":
    Scraper()