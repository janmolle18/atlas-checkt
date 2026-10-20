#!/usr/bin/env python3
"""Holt frei lizenzierte Dateien von Wikimedia Commons (nur stdlib).

Anfrage (medien/anfrage_<slug>.json):
  {"slug": "nato", "max_mb": 200,
   "suchen": [{"q": "NATO summit 2025", "n": 4, "typ": "bild"}],   # typ bild|video
   "dateien": ["File:Name.jpg"]}                                     # gezielt
Ergebnis: medien/commons/<slug>/NN_<name>.<ext> und liste.json mit Lizenzangaben.
Bereits vorhandene Titel werden übersprungen, die Anfrage kann also wachsen.
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from html import unescape

API = 'https://commons.wikimedia.org/w/api.php'
UA = {'User-Agent': 'atlas-checkt-medien/1.0 (github.com/janmolle18/insta-news-acc)'}
FREI = re.compile(r'^(public domain|pd|cc0|cc[- ]by(-sa)?([- ]\d\.\d)?|cc[- ]by(-sa)?[- ][\d.]+.*|attribution|no restrictions)', re.I)


def get(url, tries=7):
    # Commons drosselt (HTTP 429): Retry-After beachten, sonst lange warten
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            warte = 2 ** i
            if getattr(e, 'code', None) == 429:
                ra = (getattr(e, 'headers', None) or {}).get('Retry-After')
                warte = int(ra) if ra and ra.isdigit() else 20 * (i + 1)
            print('  warte', warte, 's', getattr(e, 'code', e))
            time.sleep(warte)


def api(**p):
    p.update(format='json', action='query', prop='imageinfo', iiprop='url|extmetadata|size|mime', iiurlwidth=1920)
    return json.loads(get(API + '?' + urllib.parse.urlencode(p)))


def text(meta, k):
    v = meta.get(k, {}).get('value', '')
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', '', str(v)))).strip()


def main(pfad):
    a = json.load(open(pfad))
    slug = a['slug']
    ziel = os.path.join(os.path.dirname(pfad), 'commons', slug)
    os.makedirs(ziel, exist_ok=True)
    lp = os.path.join(ziel, 'liste.json')
    liste = json.load(open(lp)) if os.path.exists(lp) else []
    have = {x['titel'] for x in liste}
    budget = a.get('max_mb', 200) * 1e6 - sum(os.path.getsize(os.path.join(ziel, x['datei'])) for x in liste if os.path.exists(os.path.join(ziel, x['datei'])))
    jobs = []
    for s in a.get('suchen', []):
        ft = 'filetype:video' if s.get('typ') == 'video' else 'filetype:bitmap'
        try:
            r = api(generator='search', gsrsearch=f"{s['q']} {ft}", gsrnamespace=6, gsrlimit=max(10, s.get('n', 3) * 4))
        except Exception as e:  # noqa: BLE001
            print('FEHLER Suche', s['q'], e); continue
        pages = sorted(r.get('query', {}).get('pages', {}).values(), key=lambda p: p.get('index', 0))
        jobs.append((s, pages))
    for t in a.get('dateien', []):
        try:
            r = api(titles=t)
            jobs.append(({'q': t, 'n': 1, 'typ': 'video' if re.search(r'\.(webm|ogv|mp4)$', t, re.I) else 'bild'}, list(r.get('query', {}).get('pages', {}).values())))
        except Exception as e:  # noqa: BLE001
            print('FEHLER Datei', t, e)
    for s, pages in jobs:
        got = 0
        for p in pages:
            if got >= s.get('n', 3):
                break
            if 'imageinfo' not in p:
                continue
            ii = p['imageinfo'][0]; m = ii.get('extmetadata', {})
            lic = text(m, 'LicenseShortName')
            if not FREI.match(lic) or 'fair use' in lic.lower() or 'non-free' in text(m, 'UsageTerms').lower():
                print('  übersprungen (Lizenz):', p['title'], lic); continue
            if p['title'] in have:
                got += 1; continue
            video = ii.get('mime', '').startswith('video')
            if s.get('typ') == 'video' and not video:
                continue
            url = ii['url'] if video else ii.get('thumburl', ii['url'])
            size = ii.get('size', 0) if video else 2e6
            if video and size > 60e6:
                print('  zu groß:', p['title'], size); continue
            if size > budget:
                print('  Budget erschöpft'); break
            name = re.sub(r'[^A-Za-z0-9]+', '_', p['title'][5:].rsplit('.', 1)[0])[:50]
            ext = urllib.parse.urlparse(url).path.rsplit('.', 1)[-1].lower()
            datei = f"{len(liste) + 1:02d}_{name}.{ext}"
            try:
                b = get(url)
            except Exception as e:  # noqa: BLE001
                print('  FEHLER Laden', p['title'], e); continue
            open(os.path.join(ziel, datei), 'wb').write(b)
            budget -= len(b)
            liste.append({'datei': datei, 'titel': p['title'], 'seite': ii.get('descriptionurl'), 'lizenz': lic,
                          'lizenz_url': text(m, 'LicenseUrl'), 'autor': text(m, 'Artist'), 'credit': text(m, 'Credit'),
                          'datum': text(m, 'DateTimeOriginal'), 'beschreibung': text(m, 'ImageDescription')[:300],
                          'breite': ii.get('width'), 'hoehe': ii.get('height'), 'mime': ii.get('mime'), 'suchbegriff': s['q']})
            have.add(p['title']); got += 1
            print('  OK', datei, lic)
            time.sleep(2)
    json.dump(liste, open(lp, 'w'), ensure_ascii=False, indent=1)
    print(slug, len(liste), 'Dateien')


if __name__ == '__main__':
    main(sys.argv[1])
