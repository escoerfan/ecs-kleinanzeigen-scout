import json
import re
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests

SUCHBEGRIFFE = [
    "Reisebus",
    "Linienbus",
    "Stadtbus",
    "LKW",
    "Sattelschlepper",
    "Kipper",
    "Betonmischer",
    "Bagger",
    "Kommunalfahrzeug",
    "Pritschenwagen",
]

BASE_URL = "https://www.kleinanzeigen.de"
RSS_TEMPLATE = "https://www.kleinanzeigen.de/s-{term}/k0.rss"

DATA_FILE = Path("angebote.json")
MAX_ALTER_TAGE = 7

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


def rss_url(suchbegriff: str) -> str:
    term = suchbegriff.lower().replace(" ", "-")
    return RSS_TEMPLATE.format(term=urllib.parse.quote(term, safe="-"))


def extrahiere_preis(description: str) -> str:
    match = re.search(r"Preis:\s*([\d.,]+\s*€)", description)
    if match:
        return match.group(1).strip()
    match = re.search(r"([\d.,]+\s*€)", description)
    if match:
        return match.group(1).strip()
    return ""


def extrahiere_ort(description: str) -> str:
    match = re.search(r"Ort:\s*([^\n<]+)", description)
    if match:
        return match.group(1).strip()
    return ""


def extrahiere_bild(description: str) -> str:
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description)
    if match:
        return match.group(1).strip()
    return ""


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extrahiere_id(link: str) -> str:
    match = re.search(r"/(\d+)(?:\.html)?$", link)
    if match:
        return match.group(1)
    return link.split("/")[-1]


def parse_datum(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    return datetime.now(timezone.utc).isoformat()


def lade_bestehende() -> dict:
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warnung: Konnte {DATA_FILE} nicht lesen: {e}")
    return {"aktualisiert": "", "anzahl": 0, "inserate": []}


def ist_zu_alt(datum_str: str) -> bool:
    if not datum_str:
        return False
    try:
        dt = datetime.fromisoformat(datum_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        grenze = datetime.now(timezone.utc) - timedelta(days=MAX_ALTER_TAGE)
        return dt < grenze
    except Exception:
        return False


def init_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        print("  Hole Session-Cookie von Startseite...")
        r = session.get(BASE_URL, timeout=15)
        print(f"  Startseite: HTTP {r.status_code}, Cookies: {dict(session.cookies)}")
        time.sleep(2)

        search_page = f"{BASE_URL}/s-nutzfahrzeuge-anhaenger/k0c215"
        r2 = session.get(search_page, timeout=15)
        print(f"  Suchseite: HTTP {r2.status_code}")
        time.sleep(2)
    except Exception as e:
        print(f"  Warnung beim Session-Init: {e}")
    return session


def scrape_feed(session: requests.Session, suchbegriff: str) -> list:
    url = rss_url(suchbegriff)
    print(f"  [{suchbegriff}] URL: {url}")
    inserate = []
    try:
        session.headers.update({"Referer": f"{BASE_URL}/s-nutzfahrzeuge-anhaenger/k0c215"})
        response = session.get(url, timeout=20)
        print(f"  [{suchbegriff}] HTTP {response.status_code}, {len(response.content)} bytes")

        if response.status_code != 200:
            body_preview = response.text[:200].replace("\n", " ")
            print(f"  [{suchbegriff}] Fehler: {body_preview}")
            return []

        preview = response.text[:150].replace("\n", " ")
        print(f"  [{suchbegriff}] Vorschau: {preview}")

        feed = feedparser.parse(response.content)

        if not feed.entries:
            print(f"  [{suchbegriff}] Keine Einträge (bozo={feed.bozo}).")
            return []

        for entry in feed.entries:
            link = getattr(entry, "link", "")
            inserat_id = extrahiere_id(link)
            description = getattr(entry, "description", "") or ""
            inserate.append({
                "id": inserat_id,
                "titel": getattr(entry, "title", "").strip(),
                "preis": extrahiere_preis(description),
                "ort": extrahiere_ort(description),
                "datum": parse_datum(entry),
                "link": link,
                "kategorie": suchbegriff,
                "bild": extrahiere_bild(description),
                "beschreibung": strip_html(description)[:300],
            })
        print(f"  [{suchbegriff}] {len(inserate)} Inserate gefunden.")
    except requests.RequestException as e:
        print(f"  [{suchbegriff}] HTTP-Fehler: {e}")
    except Exception as e:
        print(f"  [{suchbegriff}] Fehler: {e}")
    return inserate


def main():
    print("=== ECS Kleinanzeigen Scout ===")
    print(f"Starte Scraping um {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    bestehend = lade_bestehende()
    bestehende_ids = {ins["id"] for ins in bestehend.get("inserate", [])}

    alle_neuen = []
    duplikate = 0

    session = init_session()

    for begriff in SUCHBEGRIFFE:
        neue = scrape_feed(session, begriff)
        time.sleep(3)
        for ins in neue:
            if ins["id"] in bestehende_ids:
                duplikate += 1
            else:
                alle_neuen.append(ins)
                bestehende_ids.add(ins["id"])

    bestehende_gefiltert = [
        ins for ins in bestehend.get("inserate", [])
        if not ist_zu_alt(ins.get("datum", ""))
    ]

    inserate_gesamt = alle_neuen + bestehende_gefiltert

    ergebnis = {
        "aktualisiert": datetime.now(timezone.utc).isoformat(),
        "anzahl": len(inserate_gesamt),
        "inserate": inserate_gesamt,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(ergebnis, f, ensure_ascii=False, indent=2)

    print(f"\n--- Ergebnis ---")
    print(f"Neue Inserate gefunden:   {len(alle_neuen)}")
    print(f"Duplikate gefiltert:      {duplikate}")
    print(f"Inserate gesamt in JSON:  {len(inserate_gesamt)}")
    print(f"Gespeichert in {DATA_FILE}")


if __name__ == "__main__":
    main()
