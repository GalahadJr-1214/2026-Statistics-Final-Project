import time
import csv
import re
from bs4 import BeautifulSoup
import cloudscraper

# This creates a session that perfectly mimics a real Chrome browser on Windows
scraper = cloudscraper.create_scraper(browser={
    'browser': 'chrome',
    'platform': 'windows',
    'desktop': True
})

BASE_URL = "https://www.basketball-reference.com"
START_YEAR = 1984 # The first year with no missing ORTG/DRTG data (manually checked)
END_YEAR = 2026

def generate_playoff_data():
    output_file = 'nba_second_round_history.csv'
    headers = ['Season', 'Team', 'Opponent', 'Games played', 'Average Points scored',
               'Average Points allowed', 'Offensive Rating', 'Defensive Rating',
               'eFG%', 'Opp eFG%', 'TOV%', 'Opp TOV%', 'ORB%', 'Opp ORB%', 'FT/FGA', 'Opp FT/FGA', 'Champion']

    # Open our target CSV file
    with open(output_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()

        for year in range(START_YEAR, END_YEAR + 1):
            print(f"\n--- Fetching {year} Season ---")
            try:
                # 1. Fetch the main playoff summary page for the given year
                url = f"{BASE_URL}/playoffs/NBA_{year}.html"
                response = scraper.get(url)
                if response.status_code != 200:
                    print(f"Skipping {year}: Got status code {response.status_code}")
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')

                # Figure out who won the championship this year
                champion_abbr = ""
                # Find the strong tag containing "League Champion"
                champ_strong = soup.find('strong', string=re.compile("League Champion", re.IGNORECASE))
                if champ_strong and champ_strong.parent:
                    champ_link = champ_strong.parent.find('a')
                    if champ_link and '/teams/' in champ_link.get('href', ''):
                        # Extract the abbreviation (e.g. /teams/CHI/1997.html -> CHI)
                        champion_abbr = champ_link['href'].split('/')[2]

                semifinals_links = []
                # Find all links on the page that correspond to the second round
                for a in soup.find_all('a', href=True):
                    # B-Ref URLs for semis look like: /playoffs/1997-nba-eastern-conference-semifinals-...
                    if 'conference-semifinals' in a['href'] and f'{year}-nba' in a['href']:
                        if a['href'] not in semifinals_links:
                            semifinals_links.append(a['href'])

                print(f"Found {len(semifinals_links)} second round series for {year}.")

                for series_url in semifinals_links:
                    # MANDATORY RATE LIMITING: Do not lower this, or your IP will be banned!
                    time.sleep(3.5)

                    full_series_url = f"{BASE_URL}{series_url}"
                    s_resp = scraper.get(full_series_url)
                    if s_resp.status_code != 200:
                        print(f"Failed to load series page: {series_url}")
                        continue

                    # CRITICAL FIX: Basketball-Reference hides tables inside HTML comments to lazy-load them!
                    # Beautiful Soup ignores comments, so we must remove the comment tags before parsing.
                    cleaned_html = s_resp.text.replace('<!--', '').replace('-->', '')
                    s_soup = BeautifulSoup(cleaned_html, 'html.parser')

                    # The Four Factors table provides reliable Offensive Ratings for both teams
                    four_factors = s_soup.find('table', id='four_factors')
                    if not four_factors:
                        print(f"  -> Skipping: Could not find 'Four Factors' table for {series_url}")
                        continue

                    tbody = four_factors.find('tbody')
                    rows = tbody.find_all('tr')
                    if len(rows) != 2:
                        continue

                    teams_data = {}
                    for row in rows:
                        team_node = row.find(['th', 'td'], {'data-stat': 'team_id'})
                        if not team_node: continue
                        team_a = team_node.find('a')
                        if not team_a: continue

                        t_name = team_a.text.strip()
                        # Extract abbreviation from the URL (e.g. /teams/CHI/1997.html -> CHI)
                        t_abbr = team_a['href'].split('/')[2]

                        # Extract wins and losses directly from the text (e.g., "SAS (4-2)")
                        team_text = team_node.text.strip()
                        wins, losses = 0, 0
                        match = re.search(r'\((\d+)-(\d+)\)', team_text)
                        if match:
                            wins = int(match.group(1))
                            losses = int(match.group(2))

                        ortg_td = row.find('td', {'data-stat': 'off_rtg'})
                        ortg = float(ortg_td.text) if ortg_td and ortg_td.text else 0.0

                        efg_td = row.find('td', {'data-stat': 'efg_pct'})
                        efg = float(efg_td.text) if efg_td and efg_td.text else 0.0

                        tov_td = row.find('td', {'data-stat': 'tov_pct'})
                        tov = float(tov_td.text) if tov_td and tov_td.text else 0.0

                        orb_td = row.find('td', {'data-stat': 'orb_pct'})
                        orb = float(orb_td.text) if orb_td and orb_td.text else 0.0

                        ft_td = row.find('td', {'data-stat': 'ft_rate'})
                        ft_rate = float(ft_td.text) if ft_td and ft_td.text else 0.0

                        # Fetch Points Per Game and calculate Total Points
                        pts_td = row.find('td', {'data-stat': 'pts_per_g'}) or row.find('td', {'data-stat': 'pts'})
                        pts_per_g = float(pts_td.text) if pts_td and pts_td.text else 0.0

                        # Initialize our tracking dictionary for this team
                        teams_data[t_abbr] = {
                            'name': t_name,
                            'abbr': t_abbr,
                            'ortg': ortg,
                            'efg': efg,
                            'tov': tov,
                            'orb': orb,
                            'ft_rate': ft_rate,
                            'avg_pts': pts_per_g,
                            'wins': wins,
                            'games': wins + losses
                        }

                    team_list = list(teams_data.values())
                    if len(team_list) != 2: continue

                    tA, tB = team_list[0], team_list[1]

                    # The advancing team is the one with more wins
                    advancing, losing = (tA, tB) if tA['wins'] > tB['wins'] else (tB, tA)

                    # Ensure the series is actually complete (they won 4 games)
                    if advancing['wins'] >= 4:
                        is_champ = (advancing['abbr'] == champion_abbr)

                        # A team's Defensive Rating is exactly equal to their Opponent's Offensive Rating!
                        writer.writerow({
                            'Season': year,
                            'Team': advancing['name'],
                            'Opponent': losing['name'],
                            'Games played': advancing['games'],
                            'Average Points scored': advancing['avg_pts'],
                            'Average Points allowed': losing['avg_pts'],
                            'Offensive Rating': advancing['ortg'],
                            'Defensive Rating': losing['ortg'],
                            'eFG%': advancing['efg'],
                            'Opp eFG%': losing['efg'],
                            'TOV%': advancing['tov'],
                            'Opp TOV%': losing['tov'],
                            'ORB%': advancing['orb'],
                            'Opp ORB%': losing['orb'],
                            'FT/FGA': advancing['ft_rate'],
                            'Opp FT/FGA': losing['ft_rate'],
                            'Champion': is_champ
                        })
                        print(f"  -> Processed: {advancing['name']} def. {losing['name']}")

                        # Debug output for the Champion
                        if is_champ:
                            print(f"      [DEBUG] CHAMPION STATS: {advancing['name']} | ORtg: {advancing['ortg']} | DRtg: {losing['ortg']} | eFG%: {advancing['efg']} | Opp eFG%: {losing['efg']}")

                        # Force Python to immediately save the buffer to the disk
                        f.flush()

            except Exception as e:
                print(f"Error processing year {year}: {e}")

if __name__ == "__main__":
    print("Starting NBA Playoff Data Extraction...")
    print("Note: This will take roughly 8-10 minutes to run to respect server limits.")
    generate_playoff_data()
    print("\nData extraction complete! You can find 'nba_second_round_history.csv' in this folder.")