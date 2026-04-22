"""Configurazione iniziale di tag_rules e groups.

Inserita al primo boot (DB vuoto) e quando l'utente chiama POST /api/seed.
Contiene SOLO keyword generiche universali (brand nazionali, categorie comuni).

Per aggiungere regole/gruppi specifici del singolo utente (nomi di persone,
commercianti locali, cognomi di famiglia, ecc.) creare un file
``server/app/local_seed.py`` (gitignored, vedi ``local_seed.py.example``) con
variabili ``EXTRA_TAG_RULES`` / ``EXTRA_GROUPS`` nello stesso formato di questo
file. ``apply_seed()`` le unirà automaticamente.
"""
from __future__ import annotations

import importlib


# (name, pattern, tag, priority)
TAG_RULES: list[tuple[str, str, str, int]] = [
    # Trading / investimenti
    ("Trading titoli",          r"(?i)compravendita\s+titoli|\btitoli\b|dividend|cedol|\bbtp\b|\bbot\b|obbligazion|rimborso\s*titoli", "trading", 10),

    # Fonti di reddito generiche
    ("Stipendio",               r"(?i)stipendio", "stipendio", 20),
    ("Benefici statali",        r"(?i)assegno\s*unico|ord:\s*inps|ord:\s*agenzia\s*entrate|bonus\s*(?:affitto|ristruttur|renzi)|rimborso\s*730", "statale", 30),

    # E-commerce
    ("E-commerce",              r"(?i)paypal|amazon|\bamzn\b|\bebay\b|zalando|aliexpress", "ecommerce", 40),

    # Bonifici
    ("Bonifici ricevuti",       r"(?i)bonifico.*(entrata|ricevut|estero)|accredito bonifico", "bonifico-in", 60),
    ("Bonifici inviati",        r"(?i)bonifico(?!.*(entrata|ricevut))", "bonifico-out", 61),

    # Casa
    ("Condominio",              r"(?i)\bcondomini|amministratore\s*condomin", "condominio", 70),

    # Cibo / locali (categorie generiche)
    ("Bar",                     r"(?i)(?<!poke\s)(?<!grill\s)\bbar[-\s]+(?!(?:ristorant|pizzer|trattor|osteria|poke|grill))[a-z]", "bar", 80),
    ("Caffetteria",             r"(?i)\bcaff[eè]|\bcaffett|\bcafe\s+[a-z]|cafe\s*pub", "caffe", 81),
    ("Gelateria/Pasticceria",   r"(?i)gelater|gelatilandia|gelatopoli|gelatomania|pasticc", "gelateria", 82),
    ("Ristorante",              r"(?i)ristorant|ristorazion|trattor|osteria|\bpub\b", "ristorante", 83),
    ("Pizzeria",                r"(?i)pizzer", "pizzeria", 84),
    ("Fast food",               r"(?i)hamburger|mcdonald|burger|sushi|\bpoke\b", "fast-food", 85),

    # Svago
    ("Cinema",                  r"(?i)multisala|\bcinema\b|uci\s*cinemas|the\s*space", "cinema", 86),
    ("Hotel/Alloggio",          r"(?i)\bhotel\b|\balbergo\b|\bresort\b|\bb\s*&\s*b\b|bed\s*and\s*breakfast|airbnb|booking\.com|agriturism", "hotel", 87),
    ("Impianti sportivi/Sci",   r"(?i)impianti\s*risalita|ski\s*pass|skipass|seggiovia|funivi|ski\s*area", "sport-impianti", 88),
    ("Negozio sport/bici",      r"(?i)decathlon|cisalfa|cicli\s|\bbike\b|biciclett", "sport-attrezzature", 89),

    # Mezzi
    ("Parcheggio",              r"(?i)parchegg", "parcheggio", 90),
    ("Carburante",              r"(?i)stazione\s*servizio|carburant|benzin|diesel|gasolio|petrol|\beni\b|eni\d|\besso\b|\bq8\b|tamoil|\bagip\b|\bip\b\s|totalerg|\bdistributore\b", "carburante", 91),
    ("Autostrada",              r"(?i)autostrad|telepass|pedagg|\baspit\b", "autostrada", 92),
    ("Auto - servizi",          r"(?i)officin|carrozzer|gommist|revision|meccanic|autolav|car\s*wash", "auto-servizi", 93),
    ("Bollo/RC auto",           r"(?i)bollo\s*auto|rc\s*auto", "auto-tasse", 94),

    # Salute
    ("Farmacia",                r"(?i)farmacia|parafarm", "farmacia", 100),
    ("Medico/Cliniche",         r"(?i)dentist|\bdott\.|dottore|ospedal|policlinic|\bclinic|casa\s*di\s*cura|laboratori|analisi|ambulator|pediatr|ortoped|fisioterap|ottic|dermatolog|\basl\b", "medico", 101),

    # Spesa / negozi generici
    ("Supermercato",            r"(?i)\bconad\b|\blidl\b|esselunga|carrefour|eurospin|\btigre\b|\btodis\b|\bcoop\b|ipercoop|simply|\bpam\b|penny\s*market|\biper\b|supermercato|supermarket|\bmarket\b", "spesa", 110),
    ("Abbigliamento",           r"(?i)intimissimi|zara|oviesse|upim|terranova|\bh\s*&\s*m\b|calzedonia|yamamay|tezenis|\boutlet\b", "abbigliamento", 115),
    ("Parrucchiere/Barbiere",   r"(?i)parrucchier|barbier", "barbiere", 116),
    ("Libreria",                r"(?i)mondadori|feltrinelli|libreria|bookstore|giunti\s*al\s*punto|cartolibreria|cartoleria", "libreria", 117),
    ("Profumeria",              r"(?i)profumeria|sephora|douglas|kiko", "profumeria", 118),
    ("Enoteca/Cantina",         r"(?i)enotec|azienda\s*vinicol|\bvinicol", "vino", 119),
    ("Ferramenta/Bricolage",    r"(?i)ferramenta|bricolage|brico\b|leroy\s*merlin|obi\b|castorama", "ferramenta", 120),
    ("Elettronica",             r"(?i)elettron|unieuro|mediaworld|media\s*world|trony|expert|euronics|comet\b", "elettronica", 121),
    ("Calzature",               r"(?i)calzatur|bata\b|geox|foot\s*locker|pittarello|pittarosso|\bscarpe\b", "calzature", 122),
    ("Vivaio/Piante",           r"(?i)vivaio|florovivai|garden\s*center", "vivaio", 123),

    # Bollette
    ("Telefonia",               r"(?i)fastweb|\btim\b|vodafone|wind\s*tre|iliad|tiscali|telecom\s*italia", "telefonia", 195),
    ("Acqua",                   r"(?i)\bacqua\s|servizio\s*idrico|acquedotto", "acqua", 196),
    ("TV",                      r"(?i)\bsky\b|netflix|disney\s*plus|prime\s*video|dazn|now\s*tv", "tv", 197),

    # Prelievi ATM (strumento di pagamento specifico)
    ("Prelievo ATM",            r"(?i)\bprelievo\b|\bprelev", "prelievo", 200),

    # Pagamenti SEPA / utenze generiche
    ("SEPA / Utenze",           r"(?i)sepa.*(direct debit|sdd)|addebito sdd|domiciliazion", "sepa", 202),

    # Imposte
    ("F24",                     r"(?i)\bf24\b|delega\s*f24|protocollo\s*delega", "f24", 210),
    ("Commissioni bancarie",    r"(?i)canone|imposta|\bbollo\b|tassa|sconto", "commissioni", 220),
]


# (name, kind, priority, [tags])
GROUPS: list[tuple[str, str, int, list[str]]] = [
    ("Entrate trading",         "income",  10,  ["trading"]),
    ("Uscite trading",          "expense", 11,  ["trading"]),
    ("Stipendio",               "income",  20,  ["stipendio"]),
    ("Benefici statali",        "income",  30,  ["statale"]),
    ("E-commerce",              "any",     40,  ["ecommerce"]),
    ("Condominio",              "expense", 70,  ["condominio"]),
    ("Colazioni/Merende",       "expense", 80,  ["bar", "caffe", "gelateria"]),
    ("Pranzi/Cene",             "expense", 81,  ["ristorante", "pizzeria", "fast-food"]),
    ("Svago",                   "expense", 85,  ["cinema", "hotel", "sport-impianti", "sport-attrezzature"]),
    ("Mezzi",                   "expense", 90,  ["parcheggio", "carburante", "autostrada", "auto-servizi", "auto-tasse"]),
    ("Mediche",                 "expense", 100, ["farmacia", "medico"]),
    ("Spesa",                   "expense", 110, ["spesa", "abbigliamento", "barbiere", "libreria", "profumeria", "vino", "ferramenta", "elettronica", "calzature", "vivaio"]),
    ("Bonifici inviati",        "expense", 120, ["bonifico-out"]),
    ("Bollette",                "expense", 195, ["telefonia", "acqua", "tv"]),
    ("Prelievi ATM",            "expense", 200, ["prelievo"]),
    ("Addebiti SEPA / Utenze",  "expense", 202, ["sepa"]),
    ("F24 / Tasse",             "expense", 210, ["f24"]),
    ("Commissioni / Imposte",   "any",     220, ["commissioni"]),
]


def _load_local_extras() -> tuple[list, list]:
    """Carica ``server/app/local_seed.py`` se presente (gitignored).
    Deve esportare ``EXTRA_TAG_RULES`` e/o ``EXTRA_GROUPS`` nello stesso formato.
    """
    try:
        mod = importlib.import_module(".local_seed", package=__package__)
    except ModuleNotFoundError:
        return [], []
    extra_rules = list(getattr(mod, "EXTRA_TAG_RULES", []) or [])
    extra_groups = list(getattr(mod, "EXTRA_GROUPS", []) or [])
    return extra_rules, extra_groups


def apply_seed(conn) -> None:
    """Cancella tag_rules+groups+group_tags e re-inserisce la configurazione seed
    (generica, più eventuali extras da ``local_seed.py``)."""
    conn.execute("DELETE FROM group_tags")
    conn.execute("DELETE FROM groups")
    conn.execute("DELETE FROM tag_rules")

    extra_rules, extra_groups = _load_local_extras()

    # Tag rules: append (non c'è vincolo di unicità)
    for name, pattern, tag, priority in (*TAG_RULES, *extra_rules):
        conn.execute(
            "INSERT INTO tag_rules (name, pattern, tag, priority) VALUES (?, ?, ?, ?)",
            (name, pattern, tag, priority),
        )

    # Groups: merge per nome — se un extra ha lo stesso name di un gruppo pubblico,
    # i suoi tag vengono aggiunti ai tag del gruppo pubblico (senza duplicati).
    merged: dict[str, tuple[str, int, list[str]]] = {}
    for name, kind, priority, tags in GROUPS:
        merged[name] = (kind, priority, list(tags))
    for name, kind, priority, tags in extra_groups:
        if name in merged:
            existing_kind, existing_priority, existing_tags = merged[name]
            # Non cambio kind/priority di un gruppo pubblico: appendo solo tag
            seen = set(existing_tags)
            for t in tags:
                if t not in seen:
                    existing_tags.append(t)
                    seen.add(t)
        else:
            merged[name] = (kind, priority, list(tags))

    # Insert ordinato per priority
    for name, (kind, priority, tags) in sorted(merged.items(), key=lambda kv: (kv[1][1], kv[0])):
        cur = conn.execute(
            "INSERT INTO groups (name, kind, priority) VALUES (?, ?, ?)",
            (name, kind, priority),
        )
        gid = cur.lastrowid
        for t in tags:
            conn.execute("INSERT INTO group_tags (group_id, tag) VALUES (?, ?)", (gid, t))
