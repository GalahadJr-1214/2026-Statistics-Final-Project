import pandas as pd
from bs4 import BeautifulSoup, Comment
from playwright.sync_api import sync_playwright
import time
import random
from io import StringIO

def get_table_html(soup, table_id):
    """Finds a table either in plain HTML or hidden inside an HTML comment."""
    table = soup.find('table', id=table_id)
    if table:
        return str(table)
    
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        if f'id="{table_id}"' in comment:
            return str(comment)
            
    return None

def scrape_raw_playoff_teams_playwright():
    START_YEAR = 1984
    END_YEAR = 2026
    all_data = []
    
    # Mapping for the Advanced table.
    ADV_COL_MAPPING = {
        'Team': 'Team',
        'ORtg': 'ORtg',
        'DRtg': 'DRtg',
        'TS%': 'TS%',
        'Offense Four Factors_eFG%': 'eFG%',
        'Offense Four Factors_TOV%': 'TOV%',
        'Offense Four Factors_ORB%': 'ORB%',
        'Offense Four Factors_FT/FGA': 'FT/FGA',
        'Defense Four Factors_eFG%': 'Opp eFG%',
        'Defense Four Factors_TOV%': 'Opp TOV%',
        'Defense Four Factors_DRB%': 'DRB%',
        'Defense Four Factors_FT/FGA': 'Opp FT/FGA'
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False, 
            args=['--disable-blink-features=AutomationControlled']
        )
        
        try:
            page = browser.new_page()
            
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            for year in range(START_YEAR, END_YEAR + 1):
                print(f"Fetching {year} Playoff Teams...", end=" ")
                url = f"https://www.basketball-reference.com/leagues/NBA_{year}.html"
                
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    
                    try:
                        page.wait_for_selector('#per_game-team', timeout=15000)
                    except Exception:
                        print("Table element never loaded. Might be a Captcha. Waiting 10s...")
                        time.sleep(10)
                    
                    time.sleep(random.uniform(4, 8))
                    
                    html = page.content()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # --- 1. Get Per Game Stats ---
                    pg_html = get_table_html(soup, 'per_game-team')
                    
                    if not pg_html:
                        print(f"\nCaptcha or block detected for {year}.")
                        print(">>> PLEASE SOLVE THE CAPTCHA IN THE BROWSER WINDOW <<<")
                        input(">>> Press Enter here once the page loads properly...")
                        
                        html = page.content()
                        soup = BeautifulSoup(html, 'html.parser')
                        pg_html = get_table_html(soup, 'per_game-team')
                        
                        if not pg_html:
                            print("Still blocked or table missing. Skipping year.")
                            continue

                    df_pg = pd.read_html(StringIO(pg_html))[0]
                    df_pg = df_pg[['Team', 'PTS']].copy()
                    df_pg = df_pg[df_pg['Team'] != 'League Average']
                    
                    # --- 2. Get Opponent PTS ---                    
                    opp_html = get_table_html(soup, 'per_game-opponent')
                    
                    if not opp_html:
                        print("Opponent table not found. Skipping year.")
                        continue
                        
                    df_opp = pd.read_html(StringIO(opp_html))[0]
                    df_opp = df_opp[['Team', 'PTS']].copy()
                    df_opp.rename(columns={'PTS': 'OPP_PTS'}, inplace=True) # Rename to avoid clash
                    df_opp = df_opp[df_opp['Team'] != 'League Average']
                    df_opp['Team'] = df_opp['Team'].str.strip()
                    
                    # Merge
                    df_pg = pd.merge(df_pg, df_opp, on='Team')
                    
                    # --- 3. Get Advanced Stats ---
                    adv_html = get_table_html(soup, 'advanced-team')
                    
                    if not adv_html:
                        print("Advanced table not found. Skipping year.")
                        continue

                    df_adv = pd.read_html(StringIO(adv_html))[0]
                    
                    # FIX: Handle MultiIndex correctly by filtering out 'Unnamed' pandas headers
                    if isinstance(df_adv.columns, pd.MultiIndex):
                        new_cols = []
                        for upper, lower in df_adv.columns:
                            upper_str, lower_str = str(upper), str(lower)
                            # If pandas filled the top level with 'Unnamed: X_level_Y', drop it
                            if 'Unnamed' in upper_str or not upper_str.strip():
                                new_cols.append(lower_str.strip())
                            else:
                                new_cols.append(f"{upper_str.strip()}_{lower_str.strip()}")
                        df_adv.columns = new_cols
                    
                    # Keep only the columns we defined in our mapping
                    existing_mapped_cols = {k: v for k, v in ADV_COL_MAPPING.items() if k in df_adv.columns}
                    df_adv = df_adv[list(existing_mapped_cols.keys())].rename(columns=existing_mapped_cols)
                    
                    missing_adv_cols = set(ADV_COL_MAPPING.values()) - set(df_adv.columns)
                    if missing_adv_cols:
                        print(f"[Warning: Missing adv cols for {year}: {missing_adv_cols}] ", end="")
                        
                    df_adv = df_adv[df_adv['Team'] != 'League Average']
                    
                    df_pg['Team'] = df_pg['Team'].str.strip()
                    df_adv['Team'] = df_adv['Team'].str.strip()
                    
                    # --- 3. Merge ---
                    df_merged = pd.merge(df_pg, df_adv, on='Team')
                    
                    # --- 4. Filter Playoff Teams ---
                    playoff_teams = df_merged[df_merged['Team'].str.contains(r'\*', regex=True, na=False)].copy()
                    playoff_teams['Team'] = playoff_teams['Team'].str.replace('*', '', regex=False).str.strip()
                    playoff_teams.insert(0, 'Year', year)
                    
                    all_data.append(playoff_teams)
                    print(f"Found {len(playoff_teams)} teams. Success.")
                    
                    if year % 5 == 0 and all_data:
                        pd.concat(all_data, ignore_index=True).to_csv('nba_playoff_teams_CHECKPOINT.csv', index=False)
                
                except Exception as e:
                    print(f"Error: {e}")

        finally:
            browser.close()

    if not all_data:
        print("No data collected!")
        return pd.DataFrame()

    final_df = pd.concat(all_data, ignore_index=True)
    return final_df

if __name__ == "__main__":
    df_raw_playoff = scrape_raw_playoff_teams_playwright()
    
    if not df_raw_playoff.empty:
        df_raw_playoff.to_csv('nba_playoff_teams_RAW_1984_2026.csv', index=False)
        print("\nDone! Saved to nba_playoff_teams_RAW_1984_2026.csv")
    else:
        print("\nFailed to scrape data. No CSV saved.")