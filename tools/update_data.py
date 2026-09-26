"""Download official JMA best tracks and Natural Earth map; no dependencies."""
import argparse
import io
import json
from pathlib import Path
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst_all.zip'
MAP_SOURCE = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson'
JMA_TYPHOON_ROOT = 'https://www.jma.go.jp/bosai/typhoon/data'


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'TyphoonMap/1.0'})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def parse_best_tracks(text):
    lines = text.splitlines()
    storms = []
    i = 0
    while i < len(lines):
        header = lines[i]
        i += 1
        if not header.strip():
            continue
        if not header.startswith('66666'):
            raise ValueError(f'Invalid header at line {i}')
        storm_id = header[6:10]
        count = int(header[12:15])
        year = int(storm_id[:2])
        year += 1900 if year >= 51 else 2000
        points = []
        for line in lines[i:i + count]:
            yy = int(line[:2])
            # Resolve the century relative to the storm year (including New Year).
            full_year = min((1900 + yy, 2000 + yy, 2100 + yy), key=lambda x: abs(x - year))
            time = datetime.strptime(str(full_year) + line[2:8], '%Y%m%d%H').replace(tzinfo=timezone.utc)
            def number(start, end):
                value = int(line[start:end].strip() or '0')
                return value if value else None
            points.append({
                't': int(time.timestamp() * 1000),
                'lat': int(line[15:18]) / 10,
                'lon': int(line[19:23]) / 10,
                'grade': int(line[13]),
                'pressure': number(24, 28),
                'wind': number(33, 36),
            })
        if len(points) != count or not points:
            raise ValueError(f'Incomplete storm {storm_id}')
        if any(a['t'] >= b['t'] for a, b in zip(points, points[1:])):
            raise ValueError(f'Unordered track {storm_id}')
        i += count
        storms.append({'id': f'{year}{storm_id[2:]}', 'year': year,
                       'number': int(storm_id[2:]), 'name': header[30:50].strip(), 'points': points})
    if not storms:
        raise ValueError('No tracks received')
    return storms


def atomic_js(path, variable, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(f'window.{variable}=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    temporary.replace(path)


def update_tracks():
    with zipfile.ZipFile(io.BytesIO(download(SOURCE))) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith('.txt'))
        storms = parse_best_tracks(archive.read(name).decode('ascii'))
    result = {'source': SOURCE, 'fetchedAt': datetime.now(timezone.utc).isoformat(), 'storms': storms}
    atomic_js(ROOT / 'data/tracks.js', 'TYPHOON_DATA', result)
    print(f'Tracks: {len(storms)} storms ({min(s["year"] for s in storms)}-{max(s["year"] for s in storms)})')
    return result


def update_map():
    geo = json.loads(download(MAP_SOURCE))
    features = []
    for feature in geo['features']:
        geometry = feature['geometry']
        polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
        selected = []
        for polygon in polygons:
            if any(95 <= p[0] <= 180 and -5 <= p[1] <= 65 for p in polygon[0]):
                selected.append([[[round(p[0], 3), round(p[1], 3)] for p in ring] for ring in polygon])
        if selected:
            features.append({'name': feature['properties']['ADMIN'], 'polygons': selected})
    atomic_js(ROOT / 'data/map.js', 'MAP_DATA', features)
    print(f'Map: {len(features)} countries / territories')


def current_storms():
    """Return active JMA typhoons with analysis and forecast points.

    This intentionally keeps forecast values separate from the historical best
    track.  The records are displayed as provisional, and the next refresh
    replaces them instead of appending a false history.
    """
    targets = json.loads(download(f'{JMA_TYPHOON_ROOT}/targetTc.json').decode('utf-8'))
    storms = []
    for target in targets:
        cyclone = target['tropicalCyclone']
        try:
            specification = json.loads(download(f'{JMA_TYPHOON_ROOT}/{cyclone}/specifications.json').decode('utf-8'))
        except (KeyError, OSError, urllib.error.URLError, json.JSONDecodeError):
            continue
        title = next((part for part in specification if part.get('part') == 'title'), {})
        points = []
        for item in specification:
            position = item.get('position', {}).get('deg')
            valid = item.get('validtime', {}).get('UTC')
            if not position or not valid:
                continue
            wind = item.get('maximumWind', {}).get('sustained', {}).get('kt')
            points.append({
                't': int(datetime.fromisoformat(valid.replace('Z', '+00:00')).timestamp() * 1000),
                'lat': float(position[0]), 'lon': float(position[1]), 'grade': 5,
                'pressure': int(item['pressure']) if item.get('pressure', '').isdigit() else None,
                'wind': int(wind) if str(wind).isdigit() else None,
                'forecast': item.get('advancedHours', 0) > 0,
                'circleKm': item.get('probabilityCircleRadius', {}).get('km'),
            })
        if not points:
            continue
        number = int(target.get('typhoonNumber', cyclone[-2:])[-2:])
        year = datetime.fromtimestamp(points[0]['t'] / 1000, timezone.utc).year
        storms.append({'id': f'{year}{number:02}', 'year': year, 'number': number,
                       'name': title.get('name', {}).get('en', ''), 'points': points,
                       'provisional': True, 'sourceId': cyclone})
    return storms


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', action='store_true', help='also refresh the base map')
    parser.add_argument('--current', action='store_true', help='print the number of currently issued typhoons')
    args = parser.parse_args()
    if args.current:
        active = current_storms()
        print(f'Active: {len(active)} (' + ', '.join(s['id'] for s in active) + ')')
    else:
        update_tracks()
        if args.map or not (ROOT / 'data/map.js').exists():
            update_map()
