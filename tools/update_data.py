"""Download official JMA best tracks and Natural Earth map; no dependencies."""
import argparse
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst_all.zip'
MAP_SOURCE = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson'
JMA_TYPHOON_ROOT = 'https://www.jma.go.jp/bosai/typhoon/data'
# 台風位置表（速報値の PDF）。ベストトラックに載るまでの数か月を埋めるのに使う。
POSITION_TABLE_ROOT = 'https://www.data.jma.go.jp/typhoon'
TRACKS = ROOT / 'data/tracks.js'
PROVISIONAL = ROOT / 'data/provisional.js'
# 位置表は頻繁には変わらないので、毎時の実行のうち6時間に1回だけ見に行く。
TABLE_INTERVAL = timedelta(hours=6)
# 番号が付かないまま消えた熱帯低気圧の記録は、この期間を過ぎたら捨てる。
UNNAMED_RETENTION = timedelta(days=14)
KNOT = 0.514444
JST = timezone(timedelta(hours=9))


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


def read_js(path, variable):
    """atomic_js で書いた window.<variable>=...; を読み戻す。ファイルが無ければ None。"""
    if not path.exists():
        return None
    raw = path.read_text(encoding='utf-8').strip()
    prefix = f'window.{variable}='
    if not raw.startswith(prefix) or not raw.endswith(';'):
        raise ValueError(f'{path.name} の形式が正しくありません。')
    return json.loads(raw[len(prefix):-1])


def update_tracks():
    with zipfile.ZipFile(io.BytesIO(download(SOURCE))) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith('.txt'))
        storms = parse_best_tracks(archive.read(name).decode('ascii'))
    result = {'source': SOURCE, 'fetchedAt': datetime.now(timezone.utc).isoformat(), 'storms': storms}
    atomic_js(TRACKS, 'TYPHOON_DATA', result)
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


def grade_from_wind(kt):
    """最大風速(kt)から気象庁ベストトラックの階級を返す。3=TS, 4=STS, 5=TY。"""
    if kt is None or kt < 48:
        return 3
    return 4 if kt < 64 else 5


def parse_typhoon_number(target):
    """targetTc の typhoonNumber から (年, 号数) を返す。番号が無い熱帯低気圧は None。"""
    digits = re.sub(r'\D', '', str(target.get('typhoonNumber') or ''))
    if not digits:
        return None
    year = 2000 + int(digits[-4:-2]) if len(digits) >= 4 else None
    return year, int(digits[-2:])


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
        depression = target.get('category') == 'TD'
        points = []
        for item in specification:
            position = item.get('position', {}).get('deg')
            valid = item.get('validtime', {}).get('UTC')
            if not position or not valid:
                continue
            wind = item.get('maximumWind', {}).get('sustained', {}).get('kt')
            wind = int(wind) if str(wind).isdigit() else None
            forecast = (item.get('advancedHours') or 0) > 0
            point = {
                't': int(datetime.fromisoformat(valid.replace('Z', '+00:00')).timestamp() * 1000),
                'lat': float(position[0]), 'lon': float(position[1]),
                'grade': 2 if depression else grade_from_wind(wind),
                'pressure': int(item['pressure']) if str(item.get('pressure', '')).isdigit() else None,
                'wind': wind,
                'forecast': forecast,
            }
            if forecast:
                point['circleKm'] = item.get('probabilityCircleRadius', {}).get('km')
            points.append(point)
        if not points:
            continue
        points.sort(key=lambda p: p['t'])
        numbered = parse_typhoon_number(target)
        year = (numbered and numbered[0]) or datetime.fromtimestamp(points[0]['t'] / 1000, timezone.utc).year
        number = numbered[1] if numbered else None
        storms.append({'id': f'{year}{number:02}' if number else None, 'year': year, 'number': number,
                       'name': title.get('name', {}).get('en', ''), 'points': points,
                       'provisional': True, 'sourceId': cyclone})
    return storms


# ---------------------------------------------------------------------------
# 暫定経路（data/provisional.js）
#
# 気象庁のベストトラックは台風が消えてから数か月後にまとめて追加されるため、
# その間の台風を次の2つから補う。どちらもベストトラックに載ったら捨てる。
#   live  : 発生中の台風の解析位置。毎時取得して貯める（過去の位置は気象庁側に残らない）。
#   table : 台風位置表の PDF（速報値）。消えた台風の経路をまとめて取れる。
# ---------------------------------------------------------------------------

ROW = re.compile(
    r'^\s*((?:\d{1,2}\s+){0,2}\d{2})\s+'      # [月] [日] 時
    r'(\d{1,2}\.\d)(?:\s*([NS]))?\s+'         # 緯度（N/S は最初の行だけ）
    r'(\d{1,3}\.\d)(?:\s*([EW]))?'            # 経度（E/W は最初の行と日付変更線を越えたとき）
    r'(?:\s+(\d{3,4}))?'                      # 中心気圧 hPa
    r'(?:\s+(\d{1,3}|--))?(?!\S)'             # 最大風速 m/s
)
TITLE = re.compile(r'(\d{4})年台風第\s*(\d+)号\s*(.*?)\s*\((\d{4})\)')


def parse_position_table(text):
    """pdftotext -raw で取り出した台風位置表（1行が1時刻）を、ベストトラックと同じ形の台風1つにする。

    時刻は日本時間で、月・日は変わったときだけ書かれる。風速の無い行は、
    「温帯低気圧」の記載より後なら温帯低気圧(6)、それ以外は熱帯低気圧(2)とみなす。
    """
    title = TITLE.search(text)
    if not title:
        raise ValueError('位置表の表題が見つかりません。')
    year, month, day = int(title.group(1)), None, None
    number_text = title.group(4)
    extratropical = False
    points = {}
    for line in text.splitlines():
        if '温帯低気圧' in line:
            extratropical = True
        row = ROW.match(line)
        if not row:
            continue
        fields = [int(v) for v in row.group(1).split()]
        hour = fields[-1]
        if len(fields) == 3:
            if month is not None and fields[0] < month:
                year += 1
            month, day = fields[0], fields[1]
        elif len(fields) == 2:
            if day is not None and fields[0] < day and month is not None:
                month += 1
                if month > 12:
                    month, year = 1, year + 1
            day = fields[0]
        if month is None or day is None or hour > 23:
            raise ValueError(f'日時を読み取れません: {line.strip()}')
        time = datetime(year, month, day, hour, tzinfo=JST)
        lat = float(row.group(2)) * (-1 if row.group(3) == 'S' else 1)
        lon = float(row.group(4))
        if row.group(5) == 'W':
            lon = 360 - lon
        wind_ms = row.group(7)
        wind = round(int(wind_ms) / KNOT) if wind_ms and wind_ms != '--' else None
        grade = grade_from_wind(wind) if wind else (6 if extratropical else 2)
        t = int(time.timestamp() * 1000)
        points[t] = {'t': t, 'lat': lat, 'lon': lon, 'grade': grade,
                     'pressure': int(row.group(6)) if row.group(6) else None, 'wind': wind}
    if len(points) < 2:
        raise ValueError('位置表から経路を読み取れません。')
    storm_year = 2000 + int(number_text[:2])
    return {'id': f'{storm_year}{number_text[2:]}', 'year': storm_year, 'number': int(number_text[2:]),
            'name': title.group(3).strip(), 'points': [points[t] for t in sorted(points)],
            'preliminary': '速報値' in text}


def pdf_to_text(data):
    executable = shutil.which('pdftotext')
    if not executable:
        raise RuntimeError('pdftotext が見つかりません（Debian/Ubuntu なら poppler-utils）。')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'table.pdf'
        path.write_bytes(data)
        result = subprocess.run([executable, '-raw', '-enc', 'UTF-8', str(path), '-'],
                                capture_output=True, check=True, timeout=60)
    return result.stdout.decode('utf-8')


def position_table_ids(year):
    """その年の位置表ページに載っている台風番号（例: '2632'）を返す。"""
    html = download(f'{POSITION_TABLE_ROOT}/position_table/table{year}.html').decode('utf-8', 'replace')
    prefix = f'{year % 100:02}'
    return sorted({n for n in re.findall(r'T(\d{4})\.pdf', html) if n.startswith(prefix)})


def collect_table(best_ids, now):
    """ベストトラックに無い台風の位置表を取り込む。"""
    years = [now.year] + ([now.year - 1] if now.month <= 3 else [])
    storms = []
    for year in years:
        for number_text in position_table_ids(year):
            if f'20{number_text}' in best_ids:
                continue
            try:
                text = pdf_to_text(download(f'{POSITION_TABLE_ROOT}/data/T{number_text}.pdf'))
                storms.append(parse_position_table(text))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f'位置表 T{number_text} を読めませんでした: {error}', file=sys.stderr)
    return storms


def merge_points(*tracks):
    """時刻ごとに1点にまとめる。後に渡したものが優先される。"""
    merged = {}
    for track in tracks:
        for point in track:
            merged[point['t']] = point
    return [merged[t] for t in sorted(merged)]


def collect_live(store, now):
    """発生中の台風の解析位置を store['live'] に足し、最新の予報で置き換える。"""
    active = current_storms()
    live = {entry['sourceId']: entry for entry in store.get('live', [])}
    seen = set()
    for storm in active:
        key = storm['sourceId']
        seen.add(key)
        entry = live.setdefault(key, {'sourceId': key, 'points': []})
        analysis = [{k: v for k, v in p.items() if k not in ('forecast', 'circleKm')}
                    for p in storm['points'] if not p['forecast']]
        entry['points'] = merge_points(entry['points'], analysis)
        entry['forecast'] = [p for p in storm['points'] if p['forecast']]
        entry['lastSeen'] = now.isoformat()
        if storm['number']:
            entry.update(id=storm['id'], year=storm['year'], number=storm['number'])
        if storm['name']:
            entry['name'] = storm['name']
    for key, entry in live.items():
        if key not in seen:
            entry.pop('forecast', None)  # 消えた台風の予報は古いので残さない
    store['live'] = list(live.values())
    return active


def build_provisional_storms(store, best_ids):
    """画面に渡す台風の一覧を作る。同じ台風は位置表を優先し、解析位置で前後を補う。"""
    storms = {}
    for table in store.get('table', []):
        storms[table['id']] = {**table, 'provisional': True, 'source': 'position-table'}
    for entry in store.get('live', []):
        if not entry.get('id'):
            continue
        storm = storms.get(entry['id'])
        if storm:
            storm['points'] = merge_points(entry['points'], storm['points'])
            storm['source'] = 'position-table+live'
        else:
            storm = storms[entry['id']] = {
                'id': entry['id'], 'year': entry['year'], 'number': entry['number'],
                'name': entry.get('name', ''), 'points': list(entry['points']),
                'provisional': True, 'source': 'live'}
        if entry.get('forecast'):
            last = storm['points'][-1]['t'] if storm['points'] else 0
            storm['points'] = storm['points'] + [p for p in entry['forecast'] if p['t'] > last]
        storm['sourceId'] = entry['sourceId']
    result = [s for s in storms.values() if s['id'] not in best_ids and s['points']]
    return sorted(result, key=lambda s: s['id'])


def update_provisional(force_table=False):
    """data/provisional.js を更新する。一部の取得に失敗しても、取れた分は書き出す。"""
    now = datetime.now(timezone.utc)
    best = read_js(TRACKS, 'TYPHOON_DATA') or {'storms': []}
    best_ids = {storm['id'] for storm in best['storms']}
    store = read_js(PROVISIONAL, 'TYPHOON_PROVISIONAL') or {}
    errors = []

    try:
        active = collect_live(store, now)
        print(f'Active: {len(active)} (' + ', '.join(s['id'] or s['sourceId'] for s in active) + ')')
    except (OSError, ValueError, KeyError) as error:
        errors.append(f'発生中の台風を取得できませんでした: {error}')

    checked = store.get('tableCheckedAt')
    if force_table or not checked or now - datetime.fromisoformat(checked) >= TABLE_INTERVAL:
        try:
            store['table'] = collect_table(best_ids, now)
            store['tableCheckedAt'] = now.isoformat()
            print(f'Position tables: {len(store["table"])} storm(s) not yet in the best track')
        except (OSError, ValueError, RuntimeError) as error:
            errors.append(f'台風位置表を取得できませんでした: {error}')

    # ベストトラックに載った台風と、番号が付かないまま消えた熱帯低気圧の古い記録を捨てる。
    store['table'] = [s for s in store.get('table', []) if s['id'] not in best_ids]
    store['live'] = [e for e in store.get('live', [])
                     if (e.get('id') or now - datetime.fromisoformat(e['lastSeen']) < UNNAMED_RETENTION)
                     and e.get('id') not in best_ids]
    store['updatedAt'] = now.isoformat()
    store['storms'] = build_provisional_storms(store, best_ids)
    atomic_js(PROVISIONAL, 'TYPHOON_PROVISIONAL', store)
    print(f'Provisional: {len(store["storms"])} storm(s) (' + ', '.join(s['id'] for s in store['storms']) + ')')
    for error in errors:
        print(error, file=sys.stderr)
    return not errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', action='store_true', help='also refresh the base map')
    parser.add_argument('--current', action='store_true', help='print the number of currently issued typhoons')
    parser.add_argument('--provisional', action='store_true',
                        help='collect provisional tracks not yet in the best track into data/provisional.js')
    parser.add_argument('--force-table', action='store_true',
                        help='with --provisional, re-read the JMA position tables now')
    args = parser.parse_args()
    if args.current:
        active = current_storms()
        print(f'Active: {len(active)} (' + ', '.join(s['id'] or s['sourceId'] for s in active) + ')')
    elif args.provisional:
        sys.exit(0 if update_provisional(args.force_table) else 1)
    else:
        update_tracks()
        if args.map or not (ROOT / 'data/map.js').exists():
            update_map()
