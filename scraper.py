import json
import re
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

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
# HTML-Suchseite in der Kategorie Nutzfahrzeuge
SEARCH_TEMPLATE = "https://www.kleinanzeigen.de/s-nutzfahrzeuge-anhaenger/{term}/k0c215"

DATA_FILE = Path("angebote.json")
MAX_ALTER_TAGE = 7

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


def search_url(suchbegriff: str) -> str:
    term = suchbegriff.lower().replace(" ", "-")
    return SEARCH_TEMPLATE.format(term=urllib.parse.quote(term, safe="-"))


def extrahiere_preis(text: str) -> str:
    match = re.search(r"([\d.,]+\s*€)", text)
    return match.group(1).strip() if match else ""


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extrahiere_id(link: str) -> str:
    match = re.search(r"/(\d+)(?:-\d+-\d+-\d+)?(?:\.html)?$", link)
    return match.group(1) if match else link.split("/")[-1]


def lade_bestehende() -> dict:
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warnung: {e}")
    return {"aktualisiert": "", "anzahl": 0, "inserate": []}


def ist_zu_alt(datum_str: str) -> bool:
    if not datum_str:
        return False
    try:
        dt = datetime.fromisoformat(datum_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < datetime.now(timezone.utc) - timedelta(days=MAX_ALTER_TAGE)
    except Exception:
        return False


def init_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        print("  Starte Session...")
        r = session.get(BASE_URL, timeout=15)
        print(f"  Startseite: HTTP {r.status_code}")
        time.sleep(2)
        r2 = session.get(f"{BASE_URL}/s-nutzfahrzeuge-anhaenger/k0c215", timeout=15)
        print(f"  Kategorieseite: HTTP {r2.status_code}")
        time.sleep(2)
    except Exception as e:
        print(f"  Session-Init Warnung: {e}")
    return session


def parse_inserate(html: str, suchbegriff: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    inserate = []

    # Kleinanzeigen verwendet <article> Tags mit data-adid
    articles = soup.find_all("article", attrs={"data-adid": True})

    if not articles:
        # Fallback: alle article Tags
        articles = soup.find_all("article")

    print(f"    {len(articles)} article-Elemente gefunden.")

    if not articles:
        # Debug: erste 500 Zeichen HTML ausgeben
        print(f"    HTML-Vorschau: {html[:500].replace(chr(10), ' ')}")

    for art in articles:
        try:
            adid = art.get("data-adid", "")

            # Titel + Link
            link_tag = art.find("a", href=re.compile(r"/s-anzeige/"))
            if not link_tag:
                link_tag = art.find("a", href=True)
            titel = link_tag.get_text(strip=True) if link_tag else ""
            href = link_tag["href"] if link_tag else ""
            link = href if href.startswith("http") else BASE_URL + href
            inserat_id = adid or extrahiere_id(link)

            # Preis
            preis_tag = art.find(class_=re.compile(r"price|preis", re.I))
            preis = preis_tag.get_text(strip=True) if preis_tag else ""
            if not preis:
                preis = extrahiere_preis(art.get_text())

            # Ort
            ort_tag = art.find(class_=re.compile(r"locality|location|ort", re.I))
            ort = ort_tag.get_text(strip=True) if ort_tag else ""

            # Datum
            datum_tag = art.find("time") or art.find(class_=re.compile(r"date|datum|zeit", re.I))
            datum_raw = ""
            if datum_tag:
                datum_raw = datum_tag.get("datetime", datum_tag.get_text(strip=True))
            datum_iso = datetime.now(timezone.utc).isoformat()
            if datum_raw:
                try:
                    # Kleinanzeigen zeigt oft "Heute, 14:30" oder ISO
                    if "T" in datum_raw or "-" in datum_raw:
                        dt = datetime.fromisoformat(datum_raw.replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        datum_iso = dt.isoformat()
                except Exception:
                    pass

            # Bild
            img_tag = art.find("img", src=True)
            bild = ""
            if img_tag:
                bild = img_tag.get("src", "") or img_tag.get("data-src", "")

            # Beschreibung
            desc_tag = art.find(class_=re.compile(r"desc|beschreibung|text", re.I))
            beschreibung = desc_tag.get_text(strip=True)[:300] if desc_tag else ""

            if not titel:
                continue

            inserate.append({
                "id": inserat_id,
                "titel": titel,
                "preis": preis,
                "ort": ort,
                "datum": datum_iso,
                "link": link,
                "kategorie": suchbegriff,
                "bild": bild,
                "beschreibung": beschreibung,
            })
        except Exception as e:
            print(f"    Parse-Fehler bei einem Inserat: {e}")
            continue

    return inserate


def scrape_seite(session: requests.Session, suchbegriff: str) -> list:
    url = search_url(suchbegriff)
    print(f"  [{suchbegriff}] URL: {url}")
    try:
        session.headers.update({"Referer": f"{BASE_URL}/s-nutzfahrzeuge-anhaenger/k0c215"})
        response = session.get(url, timeout=20)
        print(f"  [{suchbegriff}] HTTP {response.status_code}, {len(response.content)} bytes")

        if response.status_code != 200:
            print(f"  [{suchbegriff}] Fehler, übersprungen.")
            return []

        inserate = parse_inserate(response.text, suchbegriff)
        print(f"  [{suchbegriff}] {len(inserate)} Inserate extrahiert.")
        return inserate

    except requests.RequestException as e:
        print(f"  [{suchbegriff}] HTTP-Fehler: {e}")
    except Exception as e:
        print(f"  [{suchbegriff}] Fehler: {e}")
    return []


def main():
    print("=== ECS Kleinanzeigen Scout ===")
    print(f"Starte Scraping um {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    bestehend = lade_bestehende()
    bestehende_ids = {ins["id"] for ins in bestehend.get("inserate", [])}

    alle_neuen = []
    duplikate = 0

    session = init_session()

    for begriff in SUCHBEGRIFFE:
        neue = scrape_seite(session, begriff)
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
