#!/usr/bin/env python3
"""Pobiera harmonogram dyżurów aptek ze strony Starostwa Powiatowego w Kraśniku
i scala go z sekcją zintegrowane.Kraśnik w powiaty.json.
Tylko biblioteka standardowa. Przy błędzie parsowania NIE zmienia pliku i kończy się kodem 1."""
import json, re, sys, urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

URL = "https://samorzad.gov.pl/web/powiat-krasnicki/harmonogram-aptek"
PLIK = "powiaty.json"
MIASTO = "Kraśnik"
DATA_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


class Tabele(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.wiersze, self._wiersz, self._komorka = [], None, None
        self.tekst = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._wiersz = []
        elif tag in ("td", "th") and self._wiersz is not None:
            self._komorka = []
        elif tag in ("br", "p", "div", "li"):
            self.tekst.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._komorka is not None and self._wiersz is not None:
            self._wiersz.append(re.sub(r"\s+", " ", "".join(self._komorka)).strip())
            self._komorka = None
        elif tag == "tr" and self._wiersz is not None:
            if self._wiersz:
                self.wiersze.append(self._wiersz)
            self._wiersz = None
        elif tag in ("p", "div", "li", "tr"):
            self.tekst.append("\n")

    def handle_data(self, data):
        if self._komorka is not None:
            self._komorka.append(data)
        self.tekst.append(data)


APTEKA_RE = re.compile(r"^(.*?)\s*(Kraśnik,\s*.+?)\s+tel\.?\s*(.+)$")
ZNACZNIKI_NAZWY = re.compile(r"\s+(mgr\b|Sp\.|sp\.|S\.A\.|Grupa\b|Polska\b|Nova Grupa|\().*$", re.I)


def cyfry(s):
    return re.sub(r"\D", "", s)


def normalizuj_godziny(s):
    s = s.strip()
    s = re.sub(r"\bdo\s+godz\.?\s*", "do ", s, flags=re.I)
    s = re.sub(r"\s*:\s*", ":", s)            # "8 :00" -> "8:00"
    s = re.sub(r"\s*[-–]\s*", "–", s)         # "8:00 - 23:00" -> "8:00–23:00"
    return s.strip()


def czysta_nazwa(surowa):
    n = ZNACZNIKI_NAZWY.sub("", surowa).strip()
    # "Apteka Nova Nova" -> "Apteka Nova"
    slowa = n.split()
    if len(slowa) >= 2 and slowa[-1].lower() == slowa[-2].lower():
        slowa = slowa[:-1]
    return " ".join(slowa)


def parsuj_wiersz(komorki, znane_nazwy=None):
    """Układ strony: ['1.', '25.09.2026 r. (piątek)', 'do godz. 23:00', '-', '-', 'Apteka ... Kraśnik, ul. X 1 tel. (81) 111 22 33']"""
    if len(komorki) < 4:
        return None
    m = DATA_RE.search(komorki[1])
    if not m:
        return None
    ostatnia = komorki[-1]
    a = APTEKA_RE.match(ostatnia)
    if not a:
        return None
    d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    godziny = []
    for k in komorki[2:-1]:
        k = k.strip()
        if k and k not in ("-", "–", "—"):
            g = normalizuj_godziny(k)
            if g not in godziny:
                godziny.append(g)
    if not godziny:
        return None
    telefon = a.group(3).strip()
    nazwa = (znane_nazwy or {}).get(cyfry(telefon)) or czysta_nazwa(a.group(1))
    return {"date": d.isoformat(), "hours": ", ".join(godziny), "name": nazwa,
            "addr": a.group(2).strip(), "phone": telefon}


def pobierz():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (dyzury-aptek-dane)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def zapisz(dane, sciezka):
    """Zapis zachowujący zwarty układ pliku (jeden wpis w linii) – małe diffy w GitHubie."""
    out = ['{\n  "wojewodztwa": {']
    woj = list(dane["wojewodztwa"].items())
    for i, (nazwa, lista) in enumerate(woj):
        out.append(f'    {json.dumps(nazwa, ensure_ascii=False)}: [')
        for j, p in enumerate(lista):
            out.append("      " + json.dumps(p, ensure_ascii=False, separators=(",", ":")) + ("," if j < len(lista) - 1 else ""))
        out.append("    ]" + ("," if i < len(woj) - 1 else ""))
    out.append("  },")
    out.append('  "zintegrowane": {')
    zint = list(dane["zintegrowane"].items())
    for i, (nazwa, lista) in enumerate(zint):
        out.append(f'    {json.dumps(nazwa, ensure_ascii=False)}: [')
        for j, p in enumerate(lista):
            out.append("      " + json.dumps(p, ensure_ascii=False, separators=(",", ":")) + ("," if j < len(lista) - 1 else ""))
        out.append("    ]" + ("," if i < len(zint) - 1 else ""))
    out.append("  }\n}")
    with open(sciezka, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")


def main(plik=PLIK, html=None):
    html = html if html is not None else pobierz()
    with open(plik, encoding="utf-8") as f:
        dane = json.load(f)
    znane = {cyfry(w["phone"]): w["name"] for w in dane["zintegrowane"].get(MIASTO, [])}
    p = Tabele()
    p.feed(html)
    nowe = [w for w in (parsuj_wiersz(r, znane) for r in p.wiersze) if w]
    if not nowe:
        tekst = re.sub(r"\n\s*\n+", "\n", "".join(p.tekst))
        print("BŁĄD: nie rozpoznano żadnych dyżurów. Wiersze tabel:", p.wiersze[:5])
        print("Fragment tekstu strony:\n", tekst[:1500])
        sys.exit(1)

    stare = {w["date"]: w for w in dane["zintegrowane"].get(MIASTO, [])}
    for w in nowe:
        stare[w["date"]] = w                      # nowe dane z urzędu mają pierwszeństwo
    granica = (date.today() - timedelta(days=14)).isoformat()
    scalone = [stare[k] for k in sorted(stare) if k >= granica]
    if scalone == dane["zintegrowane"].get(MIASTO):
        print("Bez zmian (%d wpisów)." % len(scalone))
        return
    dane["zintegrowane"][MIASTO] = scalone
    zapisz(dane, plik)
    print("Zaktualizowano: %d wpisów, od %s do %s." % (len(scalone), scalone[0]["date"], scalone[-1]["date"]))


if __name__ == "__main__":
    main()
