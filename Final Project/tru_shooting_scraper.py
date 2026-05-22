import time
import csv
import re
from bs4 import BeautifulSoup
import cloudscraper

# Setup Chrome mimic to bypass Cloudflare
scraper = cloudscraper.create_scraper(browser={
    'browser': 'chrome',
    'platform': 'windows',
    'desktop': True
})

BASE_URL = "https://www.basketball-reference.com"
START_YEAR = 1984
END_YEAR = 2026 

def generate_ts_data():
    output_file = 'nba_true_shooting_data.csv'
    
    # Headers focused specifically on the TS% components for both teams
    headers = ['Season', 'Team', 'Opponent', 
               'Team PTS', 'Team FGA', 'Team FTA', 'Team TS%', 
               'Opp PTS', 'Opp FGA', 'Opp FTA', 'Opp TS%']
               
    with open(output_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        
        for year in range(START_YEAR, END_YEAR + 1):
            print(f"\n--- Fetching TS% Data for {year} Season ---")
            try:
                # 1. Fetch main playoff page to get series links
                url = f"{BASE_URL}/playoffs/NBA_{year}.html"
                response = scraper.get(url)
                if response.status_code != 200:
                    continue
                    
                soup = BeautifulSoup(response.text, 'html.parser')
                semifinals_links = []
                
                for a in soup.find_all('a', href=True):
                    if 'conference-semifinals' in a['href'] and f'{year}-nba' in a['href']:
                        if a['href'] not in semifinals_links:
                            semifinals_links.append(a['href'])
                            
                for series_url in semifinals_links:
                    time.sleep(3.5) # Mandatory rate limit
                    
                    s_resp = scraper.get(f"{BASE_URL}{series_url}")
                    if s_resp.status_code != 200:
                        continue
                        
                    # Remove HTML comments to expose all tables
                    cleaned_html = s_resp.text.replace('<!--', '').replace('-->', '')
                    s_soup = BeautifulSoup(cleaned_html, 'html.parser')
                    
                    # 2. Use Four Factors to determine who played and who won
                    four_factors = s_soup.find('table', id='four_factors')
                    if not four_factors: continue
                    
                    teams_meta = {}
                    for row in four_factors.find('tbody').find_all('tr'):
                        team_node = row.find(['th', 'td'], {'data-stat': 'team_id'})
                        if not team_node or not team_node.find('a'): continue
                        
                        t_name = team_node.find('a').text.strip()
                        t_abbr = team_node.find('a')['href'].split('/')[2] 
                        
                        match = re.search(r'\((\d+)-(\d+)\)', team_node.text)
                        wins = int(match.group(1)) if match else 0
                        teams_meta[t_abbr] = {'name': t_name, 'wins': wins}
                        
                    if len(teams_meta) != 2: continue
                    
                    # 3. Locate the Basic Stats table for EACH team to get PTS, FGA, FTA
                    ts_data = {}
                    for abbr, meta in teams_meta.items():
                        # B-Ref names the Basic Stats table ID after the team abbreviation (e.g., id="SAS")
                        stat_table = s_soup.find('table', id=abbr)
                        if not stat_table: continue
                        
                        # The "Team Totals" are always stored in the table footer (tfoot)
                        tfoot = stat_table.find('tfoot')
                        if not tfoot: continue
                        
                        totals_row = tfoot.find('tr')
                        if not totals_row: continue
                        
                        # Extract the raw counting stats for the whole series
                        pts = float(totals_row.find('td', {'data-stat': 'pts'}).text)
                        fga = float(totals_row.find('td', {'data-stat': 'fga'}).text)
                        fta = float(totals_row.find('td', {'data-stat': 'fta'}).text)
                        
                        # Apply the True Shooting Percentage Formula!
                        ts_pct = pts / (2 * (fga + 0.44 * fta)) * 100
                        
                        ts_data[abbr] = {
                            'name': meta['name'],
                            'wins': meta['wins'],
                            'pts': pts, 
                            'fga': fga, 
                            'fta': fta, 
                            'ts_pct': ts_pct
                        }
                        
                    if len(ts_data) != 2: continue
                    
                    team_list = list(ts_data.values())
                    tA, tB = team_list[0], team_list[1]
                    
                    # Sort out the winner and loser
                    advancing, losing = (tA, tB) if tA['wins'] > tB['wins'] else (tB, tA)
                    
                    # Write to CSV
                    writer.writerow({
                        'Season': year,
                        'Team': advancing['name'],
                        'Opponent': losing['name'],
                        'Team PTS': advancing['pts'],
                        'Team FGA': advancing['fga'],
                        'Team FTA': advancing['fta'],
                        'Team TS%': round(advancing['ts_pct'], 4), # Rounded to 4 decimals for clean viewing
                        'Opp PTS': losing['pts'],
                        'Opp FGA': losing['fga'],
                        'Opp FTA': losing['fta'],
                        'Opp TS%': round(losing['ts_pct'], 4)
                    })
                    print(f"  -> Extracted TS% Data: {advancing['name']} vs {losing['name']}")
                    f.flush()
                    
            except Exception as e:
                print(f"Error processing year {year}: {e}")
                
if __name__ == "__main__":
    print("Starting TS% Data Extraction...")
    generate_ts_data()
    print("\nExtraction complete! Check 'nba_true_shooting_data.csv'")