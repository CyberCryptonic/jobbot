import json, urllib.parse, urllib.request
from pathlib import Path

env = {}
for line in Path(__file__).resolve().parent.parent / '.env'.read_text().splitlines():
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k] = v

params = urllib.parse.urlencode({
    'Keyword': 'cybersecurity',
    'LocationName': 'New York',
    'ResultsPerPage': 5,
})
req = urllib.request.Request(
    f'https://data.usajobs.gov/api/search?{params}',
    headers={
        'Host': 'data.usajobs.gov',
        'User-Agent': env['USAJOBS_EMAIL'],
        'Authorization-Key': env['USAJOBS_API_KEY'],
    },
)

with urllib.request.urlopen(req, timeout=20) as r:
    data = json.load(r)

result = data['SearchResult']
print(f"USAJOBS OK — {result['SearchResultCountAll']} total matches")
for item in result.get('SearchResultItems', [])[:5]:
    d = item['MatchedObjectDescriptor']
    print(f"  {d['PositionTitle']} · {d['OrganizationName']}")
