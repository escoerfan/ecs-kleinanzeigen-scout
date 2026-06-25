import json
import re
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SUCHBEGRIFFE = [
    # SZM / Sattelzugmaschinen
    "Sattelzugmaschine",
    "Sattelschlepper",
    # Kipper — nur hochwertige Markenfahrzeuge
    "Schmitz Kipper",
    "Mercedes Kipper",
    "MAN Kipper",
    "Volvo Kipper",
    "Scania Kipper",
    "DAF Kipper",
    # Auflieger
    "Sattelauflieger",
    "Planenauflieger",
    "Kofferauflieger",
    "Kühlauflieger",
    # Betonmischer-Auflieger (Trommel auf SZM)
    "Betonmischer Auflieger",
    "Fahrmischer Auflieger",
    # Radlader
    "Radlader",
    "Kubota Radlader",
    # Busse
    "Reisebus",
    "Linienbus",
]

# Kategorie-Gruppen für die Filter-Pills in der UI
KATEGORIE_GRUPPEN = {
    "Sattelzugmaschine":      "SZM",
    "Sattelschlepper":        "SZM",
    "Schmitz Kipper":         "Kipper",
    "Mercedes Kipper":        "Kipper",
    "MAN Kipper":             "Kipper",
    "Volvo Kipper":           "Kipper",
    "Scania Kipper":          "Kipper",
    "DAF Kipper":             "Kipper",
    "Sattelauflieger":        "Auflieger",
    "Planenauflieger":        "Auflieger",
    "Kofferauflieger":        "Auflieger",
    "Kühlauflieger":          "Auflieger",
    "Betonmischer Auflieger": "Betonmischer",
    "Fahrmischer Auflieger":  "Betonmischer",
    "Radlader":               "Radlader",
    "Kubota Radlader":        "Radlader",
    "Reisebus":               "Bus",
    "Linienbus":              "Bus",
}

BASE_URL = "https://www.kleinanzeigen.de"
SEARCH_TEMPLATE = "https://www.kleinanzeigen.de/s-nutzfahrzeuge-anhaenger/{term}/k0c215"
SEARCH_TEMPLATE_SEITE = "https://www.kleinanzeigen.de/s-nutzfahrzeuge-anhaenger/{term}/seite:{page}/k0c215"

MAX_SEITEN = 10

BEKANNTE_MARKEN = [
    "MAN", "Mercedes-Benz", "Mercedes", "Daimler",
    "Volvo", "Scania", "DAF", "Iveco", "Renault Trucks",
    "Setra", "Neoplan", "Evobus",
    "Liebherr", "Caterpillar", "CAT", "Komatsu", "Terex",
    "Kubota", "JCB", "Wacker Neuson",
    "Fliegl", "Krone", "Schmitz Cargobull", "Schmitz", "Schwarzmüller",
    "Wielton", "Kässbohrer", "Kassbohrer",
]

# Maßstab-Regex: filtert Spielzeug-/Modellinserate mit Verhältnisangabe wie 1:87, 1:50 …
RATIO_RE = re.compile(r"\b1\s*:\s*\d{1,3}\b")

BLACKLIST = [
    # Vermietung
    "mieten", "vermieten", "vermietung", "miete", "mietwagen", "leihwagen",
    # Spielzeug / Modelle / Sammlerstücke
    "modell", "spielzeug", "modellauto", "miniatur", "miniatür",
    "lego", "playmobil", "märklin", "marklin", "spur h0", "spur n",
    "sammler", "diecast",
    "1:87", "1:50", "1:43", "1:32", "1:18", "1:25", "1:16", "1:14",
    "1:12", "1:10", "1:8", "1:76", "1:160", "1:120", "1:35", "1:64",
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

# Händler-Erkennungs-Keywords — gewerbliche Anbieter ausschließen
HAENDLER_KEYWORDS = [
    # Automobil-Händler
    "autohaus", "automobile gmbh", "automobil gmbh", "automobil ag",
    "automobile ag", "automobile center", "auto center gmbh",
    "automobil center",
    # Fahrzeughandel
    "fahrzeughandel", "fahrzeughändler", "fahrzeughaendler",
    "nutzfahrzeughandel", "nutzfahrzeughändler", "nutzfahrzeughaendler",
    "nutzfahrzeuge gmbh", "nutzfahrzeuge ag", "nutzfahrzeugcenter",
    "nutzfahrzeug center", "nutzfahrzeug-center",
    # NFZ-Händler
    "nfz-handel", "nfz handel", "nfz center", "nfz gmbh",
    "nfz-center", "nfz-händler", "nfz haendler", "nfz-haendler",
    # LKW-Handel
    "lkw-handel", "lkw handel", "lkw center", "lkw-center",
    "lkw händler", "lkw haendler", "lkw verkauf", "lkw-verkauf",
    "kfz-handel", "kfz handel", "kfz-händler",
    # Truck Center
    "truck center", "truckcenter", "truck dealer", "truck shop", "truckshop",
    # Flottenauflösung / Fuhrpark
    "flottenauflösung", "flottenauflosung", "flottenbetrieb",
    "fuhrparkauflösung", "fuhrparkauflosung",
    # Lagerbestand
    "lagerfahrzeug", "lagerbestand", "großes lager",
    # Vorführfahrzeug
    "vorführfahrzeug", "vorfuhrfahrzeug",
    # Händler-Formulierungen
    "wir verkaufen", "unser fuhrpark", "aus unserem fuhrpark",
    "händleranfragen", "haendleranfragen",
    "gewerblicher verkauf", "gewerblich verkauf",
    "weitere fahrzeuge verfügbar", "weitere fahrzeuge auf anfrage",
    "sofort verfügbar mehrere", "mehrere einheiten",
    # Vertragspartner / Niederlassungen
    "niederlassung", "vertragshändler", "vertragswerkstatt",
    # Fahrzeugbörse / An- und Verkauf
    "fahrzeugbörse", "fahrzeugboerse",
    "an- und verkauf", "ankauf und verkauf", "inzahlungnahme",
    # Autohaus / Auto-Handel
    "auto haus", "autohandel", "auto handel", "autohändler", "autohaendler",
    "autocenter", "auto center", "autozentrum", "auto zentrum",
    "autoagentur", "autovertrieb", "auto vertrieb",
    "autobörse", "autoboerse", "automarkt", "auto markt",
    "autoexport", "auto export", "autoimport", "auto import",
    # Automobil
    "automobilhandel", "automobil handel", "automobilhändler", "automobil haendler",
    "automobilcenter", "automobilzentrum", "automobil zentrum",
    "automobilvertrieb", "automobil vertrieb", "automobilagentur", "automobil agentur",
    # KFZ
    "kfzhandel", "kfz händler", "kfzhaendler",
    "kfzvertrieb", "kfz vertrieb",
    "kfzboerse", "kfz börse",
    "kfz export", "kfzexport", "kfz import", "kfzimport",
    # Kraftfahrzeug
    "kraftfahrzeughandel", "kraftfahrzeug handel",
    "kraftfahrzeughändler", "kraftfahrzeug haendler",
    # Gebrauchtwagen
    "gebrauchtwagenhandel", "gebrauchtwagen handel",
    "gebrauchtwagenhändler", "gebrauchtwagen haendler",
    "gebrauchtwagenzentrum", "gebrauchtwagen zentrum",
    "gebrauchtwagencenter", "gebrauchtwagen center",
    "wagenhandel", "wagen handel",
    # Fahrzeug (Ergänzungen)
    "fahrzeug handel", "fahrzeug haendler",
    "fahrzeugcenter", "fahrzeug center",
    "fahrzeugzentrum", "fahrzeug zentrum",
    "fahrzeugvertrieb", "fahrzeug vertrieb",
    "fahrzeugagentur", "fahrzeug agentur",
    "fahrzeugmarkt", "fahrzeugexport", "fahrzeug export",
    "fahrzeugimport", "fahrzeug import",
    "fahrzeugverwertung", "fuhrparkverwertung",
    # Englische Begriffe / Car-Dealer
    "car center", "carcenter", "car trade", "cartrade", "car trading",
    "vehicle trade", "vehicle trading", "vehicle dealer",
    "commercial vehicle dealer", "commercial vehicle",
    "dealer vehicles", "dealer cars", "dealer trucks",
    "used trucks", "used truck dealer",
    "commercial trucks", "commercial truck sales",
    # Nutzfahrzeuge (Ergänzungen)
    "nutzfahrzeuge handel", "nutzfahrzeuge händler", "nutzfahrzeuge haendler",
    "nutzfahrzeuge zentrum", "nutzfahrzeuge center",
    "nutzfahrzeugvertrieb", "nutzfahrzeug vertrieb",
    "nutzfahrzeugboerse", "nutzfahrzeugmarkt",
    "nutzfahrzeugexport", "nutzfahrzeug export",
    "gebrauchte nutzfahrzeuge", "gebraucht nutzfahrzeuge",
    "nutzfahrzeug an und verkauf", "nutzfahrzeugverkauf",
    "nfzhandel", "nfz händler", "nfzzentrum", "nfz zentrum",
    # LKW (Ergänzungen)
    "lkwhandel", "lkwhaendler", "lkwzentrum", "lkw zentrum", "lkwcenter",
    "lkw export", "lkwexport", "lkw vertrieb", "lkwvertrieb",
    "lkwmarkt", "lkw markt", "lkw an und verkauf", "lkw verkauf händler",
    # Truck (Ergänzungen)
    "truckhandel", "truck händler", "truckhaendler",
    "truckzentrum", "truck zentrum",
    "truck export", "truckexport", "truck vertrieb", "truckvertrieb",
    "truckmarkt", "truck market", "truck sales", "trucks handel",
    "truck store", "truckstore", "truckbörse", "truckboerse",
    # Transporter / Van / Sprinter / Crafter
    "transporterhandel", "transporter handel",
    "transporterhändler", "transporter haendler",
    "transporterzentrum", "transporter zentrum",
    "transportercenter", "transporter center",
    "transporterverkauf",
    "sprinterhandel", "sprinter handel", "sprinter händler", "sprinterhaendler",
    "crafterhandel", "crafter handel", "crafter händler", "crafterhaendler",
    "van handel", "vanhandel", "van händler", "vanhaendler",
    "van center", "vancenter",
    # Bus / Omnibus / Reisebus
    "bushandel", "bus handel", "bus händler", "bushaendler",
    "buszentrum", "bus zentrum", "buscenter", "bus center",
    "omnibushandel", "omnibus handel", "omnibus händler", "omnibushaendler",
    "omnibuszentrum", "omnibus zentrum", "omnibuscenter", "omnibus center",
    "reisebushandel", "reisebus handel", "reisebus händler", "reisebushaendler",
    "linienbushandel", "linienbus handel", "linienbus händler", "linienbushaendler",
    "bus depot", "bus sales", "coach dealer", "coach sales",
    "used buses", "used bus dealer",
    # Baumaschinen / Kommunalfahrzeuge
    "baumaschinenhandel", "baumaschinen handel",
    "baumaschinenhändler", "baumaschinen haendler",
    "baumaschinenzentrum", "baumaschinen zentrum",
    "baumaschinencenter", "baumaschinen center",
    "maschinenhandel", "maschinen handel", "maschinenhändler", "maschinen haendler",
    "kommunalfahrzeughandel", "kommunalfahrzeug handel",
    "kommunalfahrzeughändler", "kommunalfahrzeug haendler",
    "kommunalfahrzeuge handel", "kommunalfahrzeuge händler",
    "kommunaltechnikhandel", "kommunaltechnik handel",
    # Anhänger / Auflieger / Trailer
    "anhängerhandel", "anhaengerhandel", "anhänger händler", "anhaenger haendler",
    "aufliegerhandel", "auflieger handel", "aufliegerhändler", "auflieger haendler",
    "trailerhandel", "trailer handel", "trailer händler", "trailerhaendler",
    "trailer center", "trailercenter",
    "sattelaufliegerhandel", "sattelauflieger handel",
    # Vertrieb / Agentur / Börse / Markt
    "nutzfahrzeugbörse", "nutzfahrzeugboerse",
    "restwertbörse", "restwertboerse",
    "remarketing", "fahrzeug remarketing", "fleet remarketing",
    "remarketing center", "remarketing zentrum",
    "gebrauchtfahrzeugzentrum", "gebrauchtfahrzeug zentrum",
    "gebrauchtfahrzeugcenter", "gebrauchtfahrzeug center",
    # Export / Import / EU
    "reimport fahrzeuge", "eu fahrzeughandel", "eu fahrzeuge handel",
    # An- und Verkauf (Ergänzungen)
    "fahrzeug an und verkauf", "auto an und verkauf",
    "kfz an und verkauf", "lkw an und verkauf",
    "fahrzeuge ankauf", "ankauf verkauf fahrzeuge",
    # Händler-Typen / gewerblich
    "markenhändler", "mehrmarkenhändler", "mehrmarken händler",
    "freier händler", "freier autohändler", "freier kfz händler", "freier fahrzeughändler",
    "gewerblicher fahrzeughändler", "gewerblicher autohändler",
    "jahreswagenhändler", "jahreswagen handel",
    "leasingrückläufer", "leasingruecklaeufer",
    "leasingfahrzeuge handel", "flottenfahrzeuge",
    "professioneller fahrzeugverkauf",
    "nutzfahrzeugverkauf händler", "transporter verkauf händler",
    "bus verkauf händler",
    # Handel mit
    "handel mit fahrzeugen", "handel mit autos",
    "handel mit lkw", "handel mit nutzfahrzeugen",
    "handel mit transportern", "handel mit bussen",
    # Wagenpark / Fuhrpark
    "wagenpark handel", "fuhrpark handel",
]

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
    if not preis_str:
        return 0.0
    zahl = re.sub(r"[^\d,.]", "", preis_str).replace(".", "").replace(",", ".")
    try:
        return float(zahl)
    except ValueError:
        return 0.0


def extrahiere_fahrzeugdaten(titel: str, beschreibung: str) -> dict:
    text = titel + " " + beschreibung
    result = {}

    bj = re.search(
        r"(?:Bj\.?|EZ\.?|Baujahr|Jg\.?)\s*((?:19|20)\d{2})\b", text, re.I
    )
    if bj:
        result["baujahr"] = bj.group(1)
    else:
        yr = re.search(r"\b((?:19[89]\d|20[012]\d))\b", titel)
        if yr:
            result["baujahr"] = yr.group(1)

    km = re.search(r"([\d.,]+)\s*km\b", text, re.I)
    if km:
        result["km"] = km.group(0).strip()

    for marke in sorted(BEKANNTE_MARKEN, key=len, reverse=True):
        if re.search(r"\b" + re.escape(marke) + r"\b", text, re.I):
            result["marke"] = marke
            break

    nl = re.search(r"([\d.,]+)\s*(?:to?\.?|tonnen)\b", text, re.I)
    if nl:
        result["nutzlast"] = nl.group(0).strip()

    return result


def ist_haendler_name(titel: str, beschreibung: str):
    t = titel.lower()
    d = beschreibung.lower()
    for wort in HAENDLER_KEYWORDS:
        if wort in t or wort in d:
            return wort
    return None


def ist_relevant(inserat: dict) -> bool:
    titel_lower = inserat.get("titel", "").lower()
    beschreibung_lower = inserat.get("beschreibung", "").lower()

    if inserat.get("haendler", False):
        return False

    if ist_haendler_name(titel_lower, beschreibung_lower):
        return False

    for wort in BLACKLIST:
        if wort in titel_lower or wort in beschreibung_lower:
            return False

    # Maßstab-Ratio (Spielzeug / Modell)
    if RATIO_RE.search(titel_lower) or RATIO_RE.search(beschreibung_lower):
        return False

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
    kategorie = KATEGORIE_GRUPPEN.get(suchbegriff, suchbegriff)

    articles = soup.find_all("article", attrs={"data-adid": True})
    if not articles:
        articles = soup.find_all("article")

    print(f"    {len(articles)} article-Elemente gefunden.")
    if not articles:
        print(f"    HTML-Vorschau: {html[:500].replace(chr(10), ' ')}")

    for art in articles:
        try:
            adid = art.get("data-adid", "")

            link_tag = art.find("a", href=re.compile(r"/s-anzeige/"))
            if not link_tag:
                link_tag = art.find("a", href=True)
            titel = link_tag.get_text(strip=True) if link_tag else ""
            href = link_tag["href"] if link_tag else ""
            link = href if href.startswith("http") else BASE_URL + href
            inserat_id = adid or extrahiere_id(link)

            preis_tag = art.find(class_=re.compile(r"price|preis", re.I))
            preis = preis_tag.get_text(strip=True) if preis_tag else ""
            if not preis:
                preis = extrahiere_preis(art.get_text())

            ort_tag = art.find(class_=re.compile(r"locality|location|ort", re.I))
            ort = ort_tag.get_text(strip=True) if ort_tag else ""

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

            img_tag = art.find("img", src=True)
            bild = ""
            if img_tag:
                bild = img_tag.get("src", "") or img_tag.get("data-src", "")

            desc_tag = art.find(class_=re.compile(r"desc|beschreibung|text", re.I))
            beschreibung = desc_tag.get_text(strip=True)[:300] if desc_tag else ""

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

            fahrzeugdaten = extrahiere_fahrzeugdaten(titel, beschreibung)

            inserate.append({
                "id": inserat_id,
                "titel": titel,
                "preis": preis,
                "ort": ort,
                "datum": datum_iso,
                "link": link,
                "kategorie": kategorie,
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
            if ins.get("haendler", False):
                gefiltert_haendler += 1
                gefiltert_gesamt += 1
                print(f"    [HÄNDLER-HTML] {ins['titel'][:60]}")
                continue
            kw = ist_haendler_name(ins.get("titel", ""), ins.get("beschreibung", ""))
            if kw:
                gefiltert_haendler += 1
                gefiltert_gesamt += 1
                print(f"    [HÄNDLER-KW '{kw}'] {ins['titel'][:60]}")
                continue
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
