import json, urllib.parse, urllib.request
from pathlib import Path

env = {}
for line in Path(__file__).resolve().parent.parent / '.env'.read_text().splitlines():
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k] = v

params = urllib.parse.urlencode({
    'app_id': env['ADZUNA_APP_ID'],
    'app_key': env['ADZUNA_APP_KEY'],
    'results_per_page': 5,
    'what': 'cybersecurity analyst',
    'where': 'Albany, NY',
    'distance': 45,
})
url = f'https://api.adzuna.com/v1/api/jobs/us/search/1?{params}'

with urllib.request.urlopen(url, timeout=20) as r:
    data = json.load(r)

print(f"ADZUNA OK — {data.get('count', 0)} total matches")
for job in data.get('results', [])[:5]:
    print(f"  {job['title']} · {job['company']['display_name']} · {job['location']['display_name']}")
