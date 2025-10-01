import json
import requests
import bs4
import pprint

base_url = "http://rcmod.the3rdage.net/wiki"

def gather_behaviors():
    html = requests.get(base_url + "/group___behavior.html").text
    soup = bs4.BeautifulSoup(html, 'html.parser')
    table = soup.find('table', {'class': 'memberdecls'})
    rows = table.find_all('tr')[1:] 
    behaviors = {}
    for row in rows:
        if len(row.find_all('td')) < 2:
                continue

        behavior_link = row.find('td', class_="memItemRight").a
        behavior_name = behavior_link.text
        behavior_url = base_url + "/" + behavior_link['href']
        behavior_html = requests.get(behavior_url).text
        behavior_soup = bs4.BeautifulSoup(behavior_html, 'html.parser')
        behavior_table = behavior_soup.find('table', {'class': 'memberdecls'})
        params = {}

        if behavior_table:
            behavior_rows = behavior_table.find_all('tr')[1:]
            for b_row in behavior_rows:
                if len(b_row.find_all('td')) < 2:
                    continue

                cols = b_row.find_all('td')
                param_type = cols[0].text.strip()
                param_name = cols[1].text.strip()
                params[param_name] = param_type

        behaviors[behavior_name] = params

    return behaviors

if __name__ == "__main__":
    behaviors = gather_behaviors()
   
    # Save pretty printed behaviors to a Python file
    with open('BFMEPlugin/behaviors_data.py', 'w', encoding='utf-8') as f:
        f.write('# Generated behaviors data\n')
        f.write('# This file contains all behaviors and their parameters\n\n')
        f.write('behaviors = ')
        f.write(json.dumps(behaviors, indent=4))
        f.write('\n')
    
    print("Behaviors data saved to 'behaviors_data.py'")
    