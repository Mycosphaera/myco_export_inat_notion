"""
enricher.py — Résolution automatique des relations Notion après import iNat.

Remplace les automations natives Notion pour :
  - Espèce (Mycoliste lookup par nom scientifique)
  - Station d'inventaire (code dans Description rapide → Stations DB)
  - Habitat général / Substrat (codes terrain → BDs Habitats / Substrats)
  - Fongarium checkbox (détection du mot "coll" dans Description rapide)

Les maps sont construites dynamiquement depuis Notion au démarrage de session —
aucune modification de code requise quand une nouvelle station ou un nouveau code est créé.
"""

import re
import time
import requests

NOTION_VERSION = "2022-06-28"

# IDs des bases de données Notion (sans tirets pour les constantes, formatés à l'usage)
DB_IDS = {
    "mycoliste":    "1d8b20f2-b231-8103-8ede-000b6155471d",
    "stations":     "21eb20f2-b231-80d1-9086-000bb5f951ef",
    "habitats":     "1ecb20f2-b231-80d2-a423-000b63e5c948",
    "substrats":    "1deb20f2-b231-80db-8afc-000b75dec26d",
    "vegetation":   "1fdb20f2-b231-80b3-9305-000bee638229",
}

# Noms des propriétés Notion dans la DB Observations (à ajuster si renommés)
PROP_ESPECE          = "Espèce"
PROP_STATION         = "Station d'inventaire"
PROP_HABITAT         = "Habitat général"
PROP_SUBSTRAT        = "Substrat"
PROP_FONGARIUM_CHECK = "Fongarium"
PROP_TAXON_ID        = "Inat Taxon ID"


# ---------------------------------------------------------------------------
# Helpers bas niveau
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _query_db_all(token: str, db_id: str) -> list:
    """Requête paginée sur une DB Notion — retourne toutes les pages."""
    results = []
    cursor = None
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(url, headers=_headers(token), json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _get_title(props: dict) -> str:
    """Extrait le texte du champ title d'une page Notion."""
    for v in props.values():
        if v.get("type") == "title" and v.get("title"):
            return v["title"][0].get("plain_text", "").strip()
    return ""


def _get_rich_text(prop: dict) -> str:
    """Extrait la valeur d'un champ rich_text Notion."""
    if prop and prop.get("type") == "rich_text" and prop.get("rich_text"):
        return prop["rich_text"][0].get("plain_text", "").strip()
    return ""


def extract_taxon_id_from_props(props: dict) -> int | None:
    """Extrait l'ID de taxon iNat depuis les propriétés Notion."""
    prop = props.get(PROP_TAXON_ID, {})
    if prop.get("type") == "number" and prop.get("number") is not None:
        try:
            return int(prop["number"])
        except (ValueError, TypeError):
            return None
    return None


def _notion_patch_with_retry(token: str, page_id: str, properties: dict) -> requests.Response:
    """PATCH Notion avec retry exponentiel sur 429."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    for attempt in range(5):
        resp = requests.patch(url, headers=_headers(token), json={"properties": properties}, timeout=30)
        if resp.status_code != 429:
            return resp
        
        try:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else (2 ** attempt + 1)
        except (ValueError, TypeError):
            wait = 2 ** attempt + 1
        time.sleep(wait)
        
    raise requests.exceptions.HTTPError(f"Échec après 5 tentatives (Status: {resp.status_code}): {resp.text}", response=resp)


# ---------------------------------------------------------------------------
# Normalisation des noms d'espèces
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    return name.lower().strip()


def _strip_infraspecific(name: str) -> str:
    """'Amanita muscaria var. muscaria' → 'Amanita muscaria'"""
    return re.sub(r'\s+(var\.|subsp\.|f\.|ssp\.|subvar\.)\s+\S+', '', name, flags=re.IGNORECASE).strip()


# ---------------------------------------------------------------------------
# 1. build_lookup_maps
# ---------------------------------------------------------------------------

def build_lookup_maps(token: str, db_ids: dict | None = None) -> dict:
    """
    Charge les maps de résolution depuis Notion.

    Retourne un dict avec :
      - species_map    : { lowercase_name → page_id }  (4700+ entrées, paginé)
      - station_map    : { CODE_MAJUSCULE → page_id }
      - habitat_codes  : { CODE_MAJUSCULE → page_id }
      - substrat_codes : { CODE_MAJUSCULE → page_id }

    À appeler une fois par session (mettre en cache dans st.session_state).
    """
    if db_ids is None:
        db_ids = DB_IDS

    maps: dict = {}
    errors: list = []

    # --- Mycoliste (4700+ taxons, requête paginée) ---
    try:
        species_map: dict   = {}  # { lowercase_name → page_id }
        taxon_id_map: dict  = {}  # { inat_taxon_id (int) → page_id }
        old_names_map: dict = {}  # { lowercase_old_name → page_id }

        pages = _query_db_all(token, db_ids["mycoliste"])
        for p in pages:
            pid   = p["id"]
            props = p["properties"]
            name  = _get_title(props)
            if name:
                species_map[_normalize(name)] = pid

            # Inat Taxon ID (number)
            tid = extract_taxon_id_from_props(props)
            if tid is not None:
                taxon_id_map[tid] = pid

            # Ancien(s) Nom (rich_text) — peut contenir plusieurs noms séparés par virgule ou point-virgule
            old_name_raw = _get_rich_text(props.get("Ancien(s) Nom", {}))
            if old_name_raw:
                for part in re.split(r"[,;]", old_name_raw):
                    part = part.strip()
                    if part:
                        old_names_map[_normalize(part)] = pid

        maps["species_map"]   = species_map
        maps["taxon_id_map"]  = taxon_id_map
        maps["old_names_map"] = old_names_map
    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        errors.append(f"Mycoliste: {e}")
        maps["species_map"]   = {}
        maps["taxon_id_map"]  = {}
        maps["old_names_map"] = {}

    # --- Stations d'inventaire ---
    try:
        station_map: dict = {}
        pages = _query_db_all(token, db_ids["stations"])
        for p in pages:
            props = p["properties"]
            # "Code de la station" est le champ dédié (rich_text)
            code = _get_rich_text(props.get("Code de la station", {}))
            if not code:
                # Fallback : le titre peut contenir le code (ex : "FSL01 — Forêt Seigneurie")
                title = _get_title(props)
                code = title.split()[0] if title else ""
            if code:
                station_map[code.upper()] = p["id"]
        maps["station_map"] = station_map
    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        errors.append(f"Stations: {e}")
        maps["station_map"] = {}

    # --- Habitats (Code terrain) ---
    try:
        habitat_codes: dict = {}
        pages = _query_db_all(token, db_ids["habitats"])
        for p in pages:
            code = _get_rich_text(p["properties"].get("Code terrain", {}))
            if code:
                habitat_codes[code.upper()] = p["id"]
        maps["habitat_codes"] = habitat_codes
    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        errors.append(f"Habitats: {e}")
        maps["habitat_codes"] = {}

    # --- Substrats (Code terrain) ---
    try:
        substrat_codes: dict = {}
        pages = _query_db_all(token, db_ids["substrats"])
        for p in pages:
            code = _get_rich_text(p["properties"].get("Code terrain", {}))
            if code:
                substrat_codes[code.upper()] = p["id"]
        maps["substrat_codes"] = substrat_codes
    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        errors.append(f"Substrats: {e}")
        maps["substrat_codes"] = {}

    maps["_errors"] = errors
    return maps


# ---------------------------------------------------------------------------
# 2. parse_description_codes
# ---------------------------------------------------------------------------

def parse_description_codes(description: str, station_map: dict, habitat_codes: dict, substrat_codes: dict) -> dict:
    """
    Extrait les codes terrain préfixés par '#' depuis Description rapide.

    Convention : tous les codes sont écrits avec '#' dans les Notes iNat.
      Exemple : "#FSL01 #coll #BOM texte libre sans risque"

    Seuls les tokens commençant par '#' sont interprétés — le texte libre
    est ignoré sans risque de faux positifs.
    Insensible à la casse : #FSL01, #fsl01, #Fsl01 sont équivalents.

    Retourne :
      {
        "station_code"      : str | None,
        "has_coll"          : bool,
        "habitat_page_ids"  : list[str],
        "substrat_page_ids" : list[str],
      }
    """
    result = {
        "station_code": None,
        "has_coll": False,
        "habitat_page_ids": [],
        "substrat_page_ids": [],
    }

    if not description:
        return result

    for token in description.split():
        if not token.startswith("#"):
            continue
        code = token[1:].upper()  # strip '#' et normaliser en majuscules
        if code == "COLL":
            result["has_coll"] = True
        elif code in habitat_codes:
            result["habitat_page_ids"].append(habitat_codes[code])
        elif code in substrat_codes:
            result["substrat_page_ids"].append(substrat_codes[code])
        elif code in station_map:
            result["station_code"] = code

    return result


# ---------------------------------------------------------------------------
# 3. match_species
# ---------------------------------------------------------------------------

def match_species(
    taxon_name: str,
    species_map: dict,
    taxon_id: int | None = None,
    taxon_id_map: dict | None = None,
    old_names_map: dict | None = None,
) -> str | None:
    """
    Résolution en 5 niveaux, du plus fiable au plus approximatif :

      1. iNat Taxon ID (int)          → match garanti, ignore les synonymes
      2. Exact match lowercase         "Amanita muscaria" → OK
      3. Ancien(s) Nom                 "Rozites caperatus" → "Cortinarius caperatus"
      4. Strip infraspécifique         "Amanita muscaria var. guessowii" → "Amanita muscaria"
      5. Genre + espèce seulement      "Russula cf. emetica" → "Russula emetica"

    Retourne le page_id Notion ou None.
    """
    # Tier 1 — iNat Taxon ID (le plus fiable, contourne les problèmes de synonymes)
    if taxon_id is not None and taxon_id_map:
        pid = taxon_id_map.get(int(taxon_id))
        if pid:
            return pid

    if not taxon_name:
        return None

    # Tier 2 — Exact match
    key = _normalize(taxon_name)
    if key in species_map:
        return species_map[key]

    # Tier 3 — Ancien(s) Nom (synonymes)
    if old_names_map and key in old_names_map:
        return old_names_map[key]

    # Tier 4 — Strip infraspécifique (var. / subsp. / f.)
    stripped = _normalize(_strip_infraspecific(taxon_name))
    if stripped != key:
        if stripped in species_map:
            return species_map[stripped]
        if old_names_map and stripped in old_names_map:
            return old_names_map[stripped]

    # Tier 5 — Genre + espèce uniquement (filtre cf. / aff. / sp.)
    parts = [p for p in stripped.split() if p not in ("cf.", "aff.", "sp.", "spp.")]
    if len(parts) >= 2:
        genus_sp = f"{parts[0]} {parts[1]}"
        if genus_sp in species_map:
            return species_map[genus_sp]
        if old_names_map and genus_sp in old_names_map:
            return old_names_map[genus_sp]

    return None


# ---------------------------------------------------------------------------
# 4. resolve_and_update_relations
# ---------------------------------------------------------------------------

def resolve_and_update_relations(
    page_id: str,
    taxon_name: str,
    description: str,
    maps: dict,
    token: str,
    db_props_schema: dict | None = None,
    taxon_id: int | None = None,
) -> tuple[bool, str]:
    """
    Résout les relations pour une observation Notion et met à jour la page.

    Paramètres :
      page_id         — ID de la page Notion à mettre à jour
      taxon_name      — Nom scientifique iNat (ex : "Amanita muscaria")
      description     — Contenu du champ Description rapide (= Notes iNat)
      maps            — Résultat de build_lookup_maps()
      token           — Token Notion
      db_props_schema — Schéma des propriétés Notion (pour détecter le nom exact du checkbox Fongarium)
      taxon_id        — ID numérique iNat du taxon (obs['taxon']['id']) — match prioritaire

    Retourne (success: bool, message: str).
    """
    species_map    = maps.get("species_map", {})
    taxon_id_map   = maps.get("taxon_id_map", {})
    old_names_map  = maps.get("old_names_map", {})
    station_map    = maps.get("station_map", {})
    habitat_codes  = maps.get("habitat_codes", {})
    substrat_codes = maps.get("substrat_codes", {})

    parsed     = parse_description_codes(description, station_map, habitat_codes, substrat_codes)
    species_id = match_species(taxon_name, species_map, taxon_id, taxon_id_map, old_names_map)

    props: dict = {}
    log: list   = []

    # Espèce
    if species_id:
        props[PROP_ESPECE] = {"relation": [{"id": species_id}]}
        log.append(f"Espèce→{taxon_name}")
    else:
        log.append(f"Espèce non trouvée ({taxon_name})")

    # Station d'inventaire
    if parsed["station_code"]:
        sid = station_map.get(parsed["station_code"])
        if sid:
            props[PROP_STATION] = {"relation": [{"id": sid}]}
            log.append(f"Station→{parsed['station_code']}")
        else:
            log.append(f"Station non trouvée ({parsed['station_code']})")

    # Fongarium checkbox ("coll")
    if parsed["has_coll"]:
        fong_key = PROP_FONGARIUM_CHECK
        if db_props_schema:
            # Détection dynamique du nom exact (au cas où renommé)
            fong_key = next(
                (k for k, v in db_props_schema.items() if "fongarium" in k.lower() and v.get("type") == "checkbox"),
                PROP_FONGARIUM_CHECK,
            )
        props[fong_key] = {"checkbox": True}
        log.append("Fongarium→✓")

    # Habitat général
    if parsed["habitat_page_ids"]:
        props[PROP_HABITAT] = {"relation": [{"id": hid} for hid in parsed["habitat_page_ids"]]}
        log.append(f"Habitat→{len(parsed['habitat_page_ids'])} lié(s)")

    # Substrat
    if parsed["substrat_page_ids"]:
        props[PROP_SUBSTRAT] = {"relation": [{"id": sid} for sid in parsed["substrat_page_ids"]]}
        log.append(f"Substrat→{len(parsed['substrat_page_ids'])} lié(s)")

    if not props:
        return False, "Rien à résoudre"

    resp = _notion_patch_with_retry(token, page_id, props)
    if resp.status_code == 200:
        return True, " | ".join(log)
    return False, f"HTTP {resp.status_code}: {resp.text[:300]}"


# ---------------------------------------------------------------------------
# 5. batch_resolve — résolution rétroactive sur un lot d'observations Notion
# ---------------------------------------------------------------------------

def batch_resolve(
    token: str,
    obs_db_id: str,
    maps: dict,
    db_props_schema: dict | None = None,
    filter_unresolved: bool = True,
    progress_callback=None,
) -> dict:
    """
    Résout les relations pour toutes les observations d'une DB Notion.

    Si filter_unresolved=True, ne traite que les pages sans relation Espèce.
    progress_callback(current, total) — appelé après chaque page traitée.

    Retourne { "success": int, "skipped": int, "errors": list[str] }.
    """
    pages = _query_db_all(token, obs_db_id)

    if filter_unresolved:
        pages = [
            p for p in pages
            if not p["properties"].get(PROP_ESPECE, {}).get("relation")
        ]

    total   = len(pages)
    success = 0
    skipped = 0
    errors  = []

    for i, page in enumerate(pages):
        page_id = page["id"]
        props   = page["properties"]

        # Récupère le nom scientifique (champ Titre)
        taxon_name = _get_title(props)

        # Récupère Description rapide
        desc_prop = props.get("Description rapide", {})
        description = _get_rich_text(desc_prop)

        # Récupère Inat Taxon ID (si présent)
        taxon_id = extract_taxon_id_from_props(props)

        if not taxon_name:
            skipped += 1
            if progress_callback:
                progress_callback(i + 1, total)
            continue

        ok, msg = resolve_and_update_relations(
            page_id, taxon_name, description, maps, token, db_props_schema, taxon_id=taxon_id
        )
        if ok:
            success += 1
        else:
            errors.append(f"{taxon_name} ({page_id[:8]}…): {msg}")

        if progress_callback:
            progress_callback(i + 1, total)

    return {"success": success, "skipped": skipped, "errors": errors, "total": total}
