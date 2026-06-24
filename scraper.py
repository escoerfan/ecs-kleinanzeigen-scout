import json
import re
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SUCHBEGRIFFE = [
    # Bustypen
    "Reisebus", "Linienbus", "Stadtbus",
    # LKW-Typen
    "LKW", "Sattelschlepper", "Kipper", "Pritschenwagen",
    "Tieflader", "Schwertransporter",
    "Tankwagen", "Tanklastzug",
    "Kranwagen", "Mobilkran", "Autokran",
    "Betonmischer",
    # Auflieger / Anhänger
    "Auflieger", "Sattelauflieger",
    "Planenauflieger", "Kofferauflieger",
    "Kühlauflieger", "Kühltransporter",
    # Baumaschinen / Kommunal
    "Bagger", "Kommunalfahrzeug",
    # Marken — Busse
    "Setra Bus", "Neoplan Bus",
    "Mercedes Bus", "MAN Bus",
    # Marken — LKW
    "MAN LKW", "Mercedes LKW",
    "Volvo LKW", "Scania LKW",
    "DAF LKW", "Iveco LKW",
]

BASE_URL = "https://www.kleinanzeigen.de"
SEARCH_TEMPLATE = "https://www.kleinanzeigen.de/s-nutzfahrzeuge-anhaenger/{term}/k0c215"
SEARCH_TEMPLATE_SEITE = "https://www.kleinanzeigen.de/s-nutzfahrzeuge-anhaenger/{term}/seite:{page}/k0c215"

# Wie viele Ergebnisseiten pro Suchbegriff maximal abrufen
MAX_SEITEN = 10

# Bekannte Fahrzeugmarken für die automatische Markenerkennung im Titel
BEKANNTE_MARKEN = [
    "MAN", "Mercedes-Benz", "Mercedes", "Daimler",
    "Volvo", "Scania", "DAF", "Iveco", "Renault Trucks",
    "Setra", "Neoplan", "Evobus",
    "Liebherr", "Caterpillar", "CAT", "Komatsu", "Terex",
    "Fliegl", "Krone", "Schmitz Cargobull", "Schmitz", "Schwarzmüller",
    "Wielton", "Kässbohrer", "Kassbohrer",
]

# Titel-Blacklist: Inserate die diese Wörter enthalten werden ignoriert
BLACKLIST = [
    # Vermietung
    "mieten", "vermieten", "vermietung", "miete", "mietwagen", "leihwagen",
    # Spielzeug / Modelle / Sammlerstücke
    "modell", "spielzeug", "modellauto", "miniatur", "miniatür",
    "lego", "playmobil", "märklin", "marklin", "spur h0", "spur n",
    "sammler", "diecast", "1:87", "1:50", "1:43", "1:32", "1:18",
    # Druckerzeugnisse / Kunst
    "gemälde", "gemalde", "bild ", "poster", "druck", "foto",
    "buch", "literatur", "roman", "zeitschrift", "heft ",
    # Aufkleber / Accessoires
    "aufkleber", "sticker", "pin ", "anstecker", "emblem",
    "t-shirt", "tasse", "kalender", "schlüsselanhänger", "schlusselanhanger",
    # Fahrschule / Führerschein
    "fahrschule", "führerschein", "fuhrerschein", "fahrstunde",
    # Gutscheine / Tickets
    "gutschein", "ticket",
    # Stellenanzeigen
    "stelle ", "stellenanzeige", "stellenangebote",
    "fahrer gesucht", "fahrerin gesucht",
    "busfahrer gesucht", "lkw-fahrer gesucht", "lkw fahrer gesucht",
    "mitarbeiter gesucht", "mitarbeiterin gesucht",
    "wir suchen", "wir stellen ein",
    "vollzeit", "teilzeit", "minijob", "aushilfe",
    "bewerbung", "gehalt", "lohn ",
]

# Händler-Erkennungs-Keywords: gewerbliche Anbieter → ignorieren
HAENDLER_KEYWORDS = [
    # Unternehmensformen im Titel — stärkstes Erkennungsmerkmal
    " gmbh", " ag ", " kg ", " ohg ", " gbr ", "gmbh & co", " e.k.",
    "gmbh&co", "co. kg",
    # Branchenbezeichnungen
    "autohaus", "fahrzeughandel", "nutzfahrzeughandel",
    "fahrzeughändler", "fahrzeughaendler",
    "nutzfahrzeughändler", "nutzfahrzeughaendler",
    "kfz-handel", "kfz handel", "kfz-händler",
    # Typische Händler-Formulierungen
    "flottenauflösung", "flottenauflosung", "flottenbetrieb",
    "lagerfahrzeug", "lagerbestand", "vorführfahrzeug",
    "vorfuhrfahrzeug", "wir verkaufen",
    "unser fuhrpark", "aus unserem fuhrpark",
    "händleranfragen", "haendleranfragen",
    "gewerblicher verkauf", "gewerblich verkauf",
    "weitere fahrzeuge verfügbar", "sofort verfügbar mehrere",
    "großes lager",
]

# Mindestpreis in € — darunter ist es vermutlich kein echtes Nutzfahrzeug
MINDESTPREIS = 500

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


def search_url(suchbegriff: str, seite: int = 1) -> str:
    term = urllib.parse.quote(suchbegriff.lower().replace(" ", "-"), safe="-")
    if seite == 1:
        return SEARCH_TEMPLATE.format(term=term)
    return SEARCH_TEMPLATE_SEITE.format(term=term, page=seite)


def extrahiere_preis(text: str) -> str:
    match = re.search(r"([\d.,]+\s*€)", text)
    return match.group(1).strip() if match else ""


def preis_als_zahl(preis_str: str) -> float:
    """Konvertiert '15.000 €' → 15000.0, gibt 0 zurück wenn nicht parsbar."""
    if not preis_str:
        return 0.0
    zahl = re.sub(r"[^\d,.]", "", preis_str).replace(".", "").replace(",", ".")
    try:
        return float(zahl)
    except ValueError:
        return 0.0


def extrahiere_fahrzeugdaten(titel: str, beschreibung: str) -> dict:
    """Liest Baujahr, Kilometerstand, Marke und Nutzlast aus Titel + Beschreibung."""
    text = titel + " " + beschreibung
    result = {}

    # Baujahr — explizit ("Bj. 2015", "EZ 2018", "Baujahr 2010")
    bj = re.search(
        r"(?:Bj\.?|EZ\.?|Baujahr|Jg\.?)\s*((?:19|20)\d{2})\b", text, re.I
    )
    if bj:
        result["baujahr"] = bj.group(1)
    else:
        # Jahreszahl im Titel allein, plausibles Fahrzeugjahr 1980–2026
        yr = re.search(r"\b((?:19[89]\d|20[012]\d))\b", titel)
        if yr:
            result["baujahr"] = yr.group(1)

    # Kilometerstand
    km = re.search(r"([\d.,]+)\s*km\b", text, re.I)
    if km:
        result["km"] = km.group(0).strip()

    # Marke — längste Übereinstimmung gewinnt (z.B. "Schmitz Cargobull" vor "Schmitz")
    for marke in sorted(BEKANNTE_MARKEN, key=len, reverse=True):
        if re.search(r"\b" + re.escape(marke) + r"\b", text, re.I):
            result["marke"] = marke
            break

    # Nutzlast / Gewicht (z.B. "7,5t", "40 Tonnen", "3.5to")
    nl = re.search(r"([\d.,]+)\s*(?:to?\.?|tonnen)\b", text, re.I)
    if nl:
        result["nutzlast"] = nl.group(0).strip()

    return result


def ist_haendler_name(titel: str, beschreibung: str):
    """Gibt den gefundenen Händler-Keyword zurück, sonst None."""
    t = titel.lower()
    d = beschreibung.lower()
    for wort in HAENDLER_KEYWORDS:
        if wort in t or wort in d:
            return wort
    return None


def ist_relevant(inserat: dict) -> bool:
    """Gibt False zurück wenn das Inserat irrelevant ist."""
    titel_lower = inserat.get("titel", "").lower()
    beschreibung_lower = inserat.get("beschreibung", "").lower()

    # Händler via HTML-Badge erkannt → raus
    if inserat.get("haendler", False):
        return False

    # Händler via Keywords → raus
    if ist_haendler_name(titel_lower, beschreibung_lower):
        return False

    # Allgemeine Blacklist (Spielzeug, Poster, Stellenanzeigen, …)
    for wort in BLACKLIST:
        if wort in titel_lower or wort in beschreibung_lower:
            return False

    # Preis-Check: wenn Preis bekannt und unter Mindestpreis → irrelevant
    preis = preis_als_zahl(inserat.get("preis", ""))
    if preis > 0 and preis < MINDESTPREIS:
        return False

    return True


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

    articles = soup.find_all("article", attrs={"data-adid": True})
    if not articles:
        articles = soup.find_all("article")

    print(f"    {len(articles)} article-Elemente gefunden.")
    if not articles:
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

            # Händler-Erkennung via HTML-Badge
            ist_haendler = False
            gewerblich_badge = art.find(
                lambda tag: tag.name in ("span", "i", "div", "small", "strong")
                and re.search(r"\bgewerblich\b", tag.get_text(), re.I)
            )
            if gewerblich_badge:
                ist_haendler = True
            if not ist_haendler:
                pro_tag = art.find(class_=re.compile(
                    r"badge.*pro|pro.*badge|seller.*type.*pro|commercial|gewerblich|pro-seller|dealer",
                    re.I
                ))
                if pro_tag:
                    ist_haendler = True

            if not titel:
                continue

            # Fahrzeugdaten aus Titel + Beschreibung extrahieren
            fahrzeugdaten = extrahiere_fahrzeugdaten(titel, beschreibung)

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
                "haendler": ist_haendler,
                **fahrzeugdaten,
            })
        except Exception as e:
            print(f"    Parse-Fehler bei einem Inserat: {e}")
            continue

    return inserate


def scrape_seite(session: requests.Session, suchbegriff: str, seite: int = 1) -> list:
    url = search_url(suchbegriff, seite)
    seite_label = f"S.{seite}" if seite > 1 else "S.1"
    print(f"  [{suchbegriff}] {seite_label} URL: {url}")
    try:
        session.headers.update({"Referer": f"{BASE_URL}/s-nutzfahrzeuge-anhaenger/k0c215"})
        response = session.get(url, timeout=20)
        print(f"  [{suchbegriff}] {seite_label} HTTP {response.status_code}, {len(response.content)} bytes")

        if response.status_code != 200:
            print(f"  [{suchbegriff}] {seite_label} Fehler, übersprungen.")
            return []

        inserate = parse_inserate(response.text, suchbegriff)
        print(f"  [{suchbegriff}] {seite_label} {len(inserate)} Inserate extrahiert.")
        return inserate

    except requests.RequestException as e:
        print(f"  [{suchbegriff}] {seite_label} HTTP-Fehler: {e}")
    except Exception as e:
        print(f"  [{suchbegriff}] {seite_label} Fehler: {e}")
    return []


def scrape_alle_seiten(session: requests.Session, suchbegriff: str) -> list:
    """Scrapet alle Seiten eines Suchbegriffs bis keine Ergebnisse mehr kommen."""
    alle = []
    for seite in range(1, MAX_SEITEN + 1):
        ergebnisse = scrape_seite(session, suchbegriff, seite)
        if not ergebnisse:
            print(f"  [{suchbegriff}] Keine weiteren Ergebnisse auf S.{seite}, stoppe.")
            break
        alle.extend(ergebnisse)
        if seite < MAX_SEITEN:
            time.sleep(2)
    return alle


def main():
    print("=== ECS Kleinanzeigen Scout ===")
    print(f"Starte Scraping um {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    bestehend = lade_bestehende()
    bestehende_ids = {ins["id"] for ins in bestehend.get("inserate", [])}

    alle_neuen = []
    duplikate = 0

    session = init_session()

    gefiltert_gesamt = 0
    gefiltert_haendler = 0
    gefiltert_inhalt = 0

    for begriff in SUCHBEGRIFFE:
        neue = scrape_alle_seiten(session, begriff)
        time.sleep(3)
        for ins in neue:
            # Händler via HTML-Badge
            if ins.get("haendler", False):
                gefiltert_haendler += 1
                gefiltert_gesamt += 1
                print(f"    [HÄNDLER-HTML] {ins['titel'][:60]}")
                continue
            # Händler via Keyword
            kw = ist_haendler_name(ins.get("titel", ""), ins.get("beschreibung", ""))
            if kw:
                gefiltert_haendler += 1
                gefiltert_gesamt += 1
                print(f"    [HÄNDLER-KW '{kw}'] {ins['titel'][:60]}")
                continue
            # Allgemeine Relevanz
            if not ist_relevant(ins):
                gefiltert_inhalt += 1
                gefiltert_gesamt += 1
                continue
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
    print(f"Gefiltert gesamt:         {gefiltert_gesamt}")
    print(f"  davon Händler:          {gefiltert_haendler}")
    print(f"  davon Inhalt/Unsinn:    {gefiltert_inhalt}")
    print(f"Duplikate gefiltert:      {duplikate}")
    print(f"Inserate gesamt in JSON:  {len(inserate_gesamt)}")
    print(f"Gespeichert in {DATA_FILE}")


if __name__ == "__main__":
    main()
