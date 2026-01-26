import pandas as pd
import json
from time import sleep
import re
from collections import defaultdict

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

options = webdriver.ChromeOptions()
options.add_argument('--headless')  # Enable headless mode
options.add_argument('--disable-gpu')  # Optional, recommended for Windows

driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()),options=options)

class Scraper():
    def __init__(self):
        self.events = defaultdict(dict)
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

    def get_events(self, driver):
        search_results = driver.find_elements(By.CSS_SELECTOR, "table.boxed > tbody > tr")
        
        print(search_results)
        
    def get_year_leaders(self, driver):
        stats_dict = {}
        key_list = []
        events = []
        leagues = []
        search_results = driver.find_elements(By.CSS_SELECTOR, "table.boxed")
        for result in search_results:
            banners = []
            cell_results = []
            rows = result.find_elements(By.TAG_NAME, "tr")
            for row in rows:
                headers = [header.text for header in row.find_elements(By.XPATH, ".//p")]
                if headers:
                    leagues.extend(headers)
                banners = [banner.text for banner in row.find_elements(By.XPATH, ".//td[contains(@class, 'banner')]")]
                if banners:
                    key_list = banners
                cells = [stat.text.strip() for stat in row.find_elements(By.XPATH, ".//td[contains(@class, 'datacolBox') or contains(@class, 'datacolBlue')]")]
                if cells:
                    if len(cells) == 1:
                        events = cells
                    else:
                        cell_results.append(cells)
            list_of_dictionaries = [dict(zip(key_list, values)) for values in cell_results]
        
    
    def log_data(self, links : list):
        for link in links:
            try:
                driver.get(link)
                # year, league = self.get_year_league(driver)
                # if year and league:
                #     self.events[year][league] = {}
                self.get_year_leaders(driver)
                break
            # TODO Currently exception is happening because American Association link also ends in a.  Need to figure out how to remove those from link list
            except Exception:
                break

if __name__ == "__main__":
    Scraper()