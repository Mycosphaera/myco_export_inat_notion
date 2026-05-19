"""
enricher.py — Résolution automatique des relations Notion après import iNat.

Remplace les automations natives Notion pour :
  - Espèce (Mycoliste lookup par nom scientifique)
  - Station d'inventaire (code dans Description rapide → Stations DB)
  - Habitat général / Substrat (codes terrain → BDs Habitats / Substrats)
  - Végétation / Hôte - substrat (codes plantes → BD Plantes)
  - Fongarium checkbox (détection du mot "coll" dans Description rapide)

Convention de codes dans le champ Notes iNat (= Description rapide après import) :
  #FSL01          → Station d'inventaire (et Projet déduit du préfixe alphabétique)
  #coll           → Fongarium (checkbox)
  !BOM            → Habitat général (via "Code terrain" de la BD Habitats)
  $BMC            → Substrat (via "Code terrain" de la BD Substrats)
  @BOJ            → Végétation (via "code_plante" de la BD Plantes)
  @@BOJ           → Hôte - substrat (via "code_plante" de la BD Plantes)
  #Acer_saccharum → Végétation (rétrocompat : nom latin avec underscore)
  Bouleau jaune   → Végétation (texte libre — match exact contre nom fr/lat/en de la BD)

Les maps sont construites dynamiquement depuis Notion au démarrage de session —
aucune modification de code requise quand une nouvelle station ou un nouveau code est créé.
"""

import re
import time
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

NOTION_VERSION = "2022-06-28"

# IDs des bases de données Notion (sans tirets pour les constantes, formatés à l'usage)
DB_IDS = {
    "mycoliste":    "1d8b20f2-b231-8166-aa5d-c1d48a5d6b25",
    "stations":     "21eb20f2-b231-8005-8889-f00269290d91",
    "habitats":     "1ecb20f2-b231-805b-ba21-edc052d574f1",
    "substrats":    "1deb20f2-b231-804d-8f5d-e5d9cf67a906",
    "vegetation":   "1fdb20f2-b231-80b4-83a4-d64e12ba5c85",
    "projets":      "34cb20f2-b231-8198-823a-000bc36fc6b3",
}

# Noms des propriétés Notion dans la DB Observations (à ajuster si renommés)
PROP_ESPECE          = "Espèce"
PROP_STATION         = "Station d'inventaire"
PROP_HABITAT         = "Habitat général"
PROP_SUBSTRAT        = "Substrat"
PROP_VEGETATION      = "Végétation"
PROP_HOTE_SUBSTRAT   = "Hôte - substrat"
PROP_FONGARIUM_CHECK = "Fongarium"
PROP_TAXON_ID        = "Inat Taxon ID"
PROP_PROJET          = "Projet d'inventaire"


# ---------------------------------------------------------------------------
# Helpers bas niveau
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _query_db_all(token: str, db_id: str, session: requests.Session | None = None, filter_properties: list[str] | None = None) -> list:
    """Requête paginée sur une DB Notion — retourne toutes les pages avec retry robuste."""
    results = []
    cursor = None
    
    # URL avec filtrage de propriétés si spécifié
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    if filter_properties:
        params = "&".join([f"filter_properties={p}" for p in filter_properties])
        url = f"{url}?{params}"
        
    requester = session if session else requests
    
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
            
        # Retry loop for the POST request
        last_resp = None
        for attempt in range(5):
            try:
                # Increased timeout to 60s for stability with large Notion databases
                resp = requester.post(url, headers=_headers(token), json=body, timeout=60)
                last_resp = resp
                
                # Success
                if resp.status_code == 200:
                    break
                    
                # Retry on 429 (Rate Limit) or 5xx (Server Error)
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    # Exponential backoff + jitter
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else (2 ** attempt + random.random())
                    except (ValueError, TypeError):
                        wait = 2 ** attempt + random.random()
                    time.sleep(wait)
                    continue
                
                # Other errors: raise immediately
                resp.raise_for_status()
                
            except requests.exceptions.HTTPError as e:
                if e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    raise
                if attempt < 4:
                    time.sleep(2 ** attempt + random.random())
                    continue
                raise
            except requests.exceptions.RequestException as e:
                # Retry on network errors
                if attempt < 4:
                    time.sleep(2 ** attempt + random.random())
                    continue
                raise
        
        if last_resp is None or last_resp.status_code != 200:
            if last_resp:
                last_resp.raise_for_status()
            raise Exception("Impossible de contacter l'API Notion après plusieurs tentatives.")
            
        data = last_resp.json()
        batch_size = len(data.get("results", []))
        results.extend(data.get("results", []))
        
        # Log progress to terminal
        print(f"  [Notion] DB {db_id[:8]}... : {len(results)} pages récupérées...")
        
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


def _notion_patch_with_retry(token: str, page_id: str, properties: dict, session: requests.Session | None = None) -> requests.Response:
    """PATCH Notion avec retry exponentiel sur 429 et erreurs réseau."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    requester = session if session else requests
    
    last_resp = None
    for attempt in range(5):
        try:
            resp = requester.patch(url, headers=_headers(token), json={"properties": properties}, timeout=30)
            last_resp = resp
            if resp.status_code not in {429, 500, 502, 503, 504}:
                return resp
            
            retry_after = resp.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else (2 ** attempt + random.random())
            except (ValueError, TypeError):
                wait = 2 ** attempt + random.random()
            time.sleep(wait)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
            if attempt < 4:
                time.sleep(2 ** attempt + random.random())
                continue
            raise
            
    if last_resp:
        raise requests.exceptions.HTTPError(f"Échec après 5 tentatives (Status: {last_resp.status_code}): {last_resp.text}", response=last_resp)
    raise Exception("Échec PATCH après 5 tentatives pour cause d'erreurs réseau.")


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
    Charge les maps de résolution depuis Notion en parallèle.
    """
    if db_ids is None:
        db_ids = DB_IDS

    maps: dict = {
        "species_map": {},
        "taxon_id_map": {},
        "old_names_map": {},
        "station_map": {},
        "habitat_codes": {},
        "substrat_codes": {},
        "vegetation_map": {},          # Nom latin (rétrocompat #Latin_name)
        "vegetation_code_map": {},     # code_plante (@CODE et @@CODE)
        "vegetation_fr_map": {},       # nom_vernaculaire_fr (bare-text)
        "vegetation_en_map": {},       # nom_vernaculaire_en (bare-text)
        "projet_map": {},
        "_errors": []
    }

    def _load_mycoliste(session):
        print(f"[Notion] Chargement de Mycoliste ({db_ids['mycoliste']})...")
        start_t = time.time()
        try:
            # Optimisation: On ne récupère que Nom Latin (title), Inat Taxon ID (NmF%3F) et Ancien(s) Nom (%3C~w%5C)
            props_to_fetch = ["title", "NmF%3F", "%3C~w%5C"]
            pages = _query_db_all(token, db_ids["mycoliste"], session=session, filter_properties=props_to_fetch)
            s_map, t_map, o_map = {}, {}, {}
            for p in pages:
                pid = p["id"]
                props = p["properties"]
                name = _get_title(props)
                if name: s_map[_normalize(name)] = pid
                tid = extract_taxon_id_from_props(props)
                if tid is not None: t_map[tid] = pid
                old_name_raw = _get_rich_text(props.get("Ancien(s) Nom", {}))
                if old_name_raw:
                    for part in re.split(r"[,;]", old_name_raw):
                        part = part.strip()
                        if part: o_map[_normalize(part)] = pid
            print(f"[Notion] Mycoliste chargée : {len(s_map)} taxons en {time.time()-start_t:.1f}s")
            return {"species_map": s_map, "taxon_id_map": t_map, "old_names_map": o_map}
        except Exception as e:
            print(f"[Notion] Erreur Mycoliste: {e}")
            return {"error": f"Mycoliste: {e}"}

    def _load_stations(session):
        print(f"[Notion] Chargement des Stations...")
        start_t = time.time()
        try:
            # Optimisation: Titre (title) et Code station (v%3A~~)
            pages = _query_db_all(token, db_ids["stations"], session=session, filter_properties=["title", "v%3A~~"])
            st_map = {}
            for p in pages:
                props = p["properties"]
                code = _get_rich_text(props.get("Code de la station", {}))
                if not code:
                    title = _get_title(props)
                    code = title.split()[0] if title else ""
                if code: st_map[code.upper()] = p["id"]
            print(f"[Notion] Stations chargées : {len(st_map)} en {time.time()-start_t:.1f}s")
            return {"station_map": st_map}
        except Exception as e:
            print(f"[Notion] Erreur Stations: {e}")
            return {"error": f"Stations: {e}"}

    def _load_habitats(session):
        print(f"[Notion] Chargement des Habitats...")
        start_t = time.time()
        try:
            # Optimisation: Titre (title) et Code (L%5DW%40)
            pages = _query_db_all(token, db_ids["habitats"], session=session, filter_properties=["title", "L%5DW%40"])
            h_map = {}
            for p in pages:
                code = _get_rich_text(p["properties"].get("Code terrain", {}))
                if code: h_map[code.upper()] = p["id"]
            print(f"[Notion] Habitats chargés : {len(h_map)} en {time.time()-start_t:.1f}s")
            return {"habitat_codes": h_map}
        except Exception as e:
            print(f"[Notion] Erreur Habitats: {e}")
            return {"error": f"Habitats: {e}"}

    def _load_substrats(session):
        print(f"[Notion] Chargement des Substrats...")
        start_t = time.time()
        try:
            # Optimisation: Titre (title) et Code (q_lR)
            pages = _query_db_all(token, db_ids["substrats"], session=session, filter_properties=["title", "q_lR"])
            su_map = {}
            for p in pages:
                code = _get_rich_text(p["properties"].get("Code terrain", {}))
                if code: su_map[code.upper()] = p["id"]
            print(f"[Notion] Substrats chargés : {len(su_map)} en {time.time()-start_t:.1f}s")
            return {"substrat_codes": su_map}
        except Exception as e:
            print(f"[Notion] Erreur Substrats: {e}")
            return {"error": f"Substrats: {e}"}

    def _load_vegetation(session):
        print(f"[Notion] Chargement de la Végétation...")
        start_t = time.time()
        try:
            # Property IDs : title (Nom latin), hNJw (code_plante),
            #                oZxm (nom_vernaculaire_fr), %3AUtU (nom_vernaculaire_en)
            pages = _query_db_all(
                token, db_ids["vegetation"], session=session,
                filter_properties=["title", "hNJw", "oZxm", "%3AUtU"],
            )
            v_latin, v_code, v_fr, v_en = {}, {}, {}, {}
            for p in pages:
                props = p["properties"]
                pid = p["id"]
                # Nom latin (title)
                latin = _get_title(props)
                if latin:
                    v_latin[_normalize(latin)] = pid
                # code_plante (rich_text) — clé en majuscules pour comparaison @CODE
                code = _get_rich_text(props.get("code_plante", {}))
                if code:
                    v_code[code.upper()] = pid
                # nom_vernaculaire_fr — peut contenir plusieurs noms séparés par ; ou ,
                fr_raw = _get_rich_text(props.get("nom_vernaculaire_fr", {}))
                if fr_raw:
                    for part in re.split(r"[,;]", fr_raw):
                        part = part.strip()
                        if part:
                            v_fr[_normalize(part)] = pid
                # nom_vernaculaire_en — idem
                en_raw = _get_rich_text(props.get("nom_vernaculaire_en", {}))
                if en_raw:
                    for part in re.split(r"[,;]", en_raw):
                        part = part.strip()
                        if part:
                            v_en[_normalize(part)] = pid
            print(
                f"[Notion] Végétation chargée : {len(v_latin)} latins, "
                f"{len(v_code)} codes, {len(v_fr)} fr, {len(v_en)} en "
                f"en {time.time()-start_t:.1f}s"
            )
            return {
                "vegetation_map": v_latin,
                "vegetation_code_map": v_code,
                "vegetation_fr_map": v_fr,
                "vegetation_en_map": v_en,
            }
        except Exception as e:
            print(f"[Notion] Erreur Végétation: {e}")
            return {"error": f"Végétation: {e}"}

    def _load_projets(session):
        print(f"[Notion] Chargement des Projets d'inventaire...")
        start_t = time.time()
        try:
            pages = _query_db_all(token, db_ids["projets"], session=session)
            p_map = {}
            for p in pages:
                props = p["properties"]
                # Champ "Code" : acronyme officiel (ex: FSL, RNFCT, LT)
                code = _get_rich_text(props.get("Code", {}))
                if code:
                    p_map[code.upper()] = p["id"]
            print(f"[Notion] Projets chargés : {len(p_map)} en {time.time()-start_t:.1f}s")
            return {"projet_map": p_map}
        except Exception as e:
            print(f"[Notion] Erreur Projets: {e}")
            return {"error": f"Projets: {e}"}

    with requests.Session() as session:
        tasks = [
            _load_mycoliste,
            _load_stations,
            _load_habitats,
            _load_substrats,
            _load_vegetation,
            _load_projets,
        ]
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(t, session) for t in tasks]
            for fut in as_completed(futures):
                res = fut.result()
                if "error" in res:
                    maps["_errors"].append(res["error"])
                else:
                    maps.update(res)

    return maps


# ---------------------------------------------------------------------------
# 2. parse_description_codes
# ---------------------------------------------------------------------------

def _extract_station_prefix(station_code: str) -> str | None:
    """
    Extrait le préfixe alphabétique d'un code station.
    Ex: 'FSL01' → 'FSL', 'LT02' → 'LT', 'RNFCT01' → 'RNFCT', 'MRD-P01' → 'MRD'
    """
    m = re.match(r'^([A-Za-z]+)', station_code)
    return m.group(1).upper() if m else None


# Caractères de ponctuation à retirer aux extrémités des tokens texte libre
_PUNCT_RE = re.compile(r'^[\s.,;:!?()\[\]"\'«»]+|[\s.,;:!?()\[\]"\'«»]+$')


def _strip_punct(token: str) -> str:
    """Enlève la ponctuation aux extrémités d'un token."""
    return _PUNCT_RE.sub("", token)


def _scan_bare_plant_names(
    bare_tokens: list[str],
    latin_map: dict,
    fr_map: dict,
    en_map: dict,
    max_ngram: int = 4,
) -> list[str]:
    """
    Scan greedy longest-first des noms de plantes (latin/fr/en) dans une liste
    de tokens texte libre. Match exact requis contre la BD.

    Retourne une liste de page_ids uniques (ordre de première occurrence).
    """
    if not bare_tokens or not (latin_map or fr_map or en_map):
        return []

    matched_ids: list[str] = []
    consumed = [False] * len(bare_tokens)
    n_tokens = len(bare_tokens)

    # Greedy : du n-gramme le plus long au plus court
    for n in range(min(max_ngram, n_tokens), 0, -1):
        for i in range(n_tokens - n + 1):
            if any(consumed[j] for j in range(i, i + n)):
                continue
            phrase = " ".join(bare_tokens[i:i + n])
            key = _normalize(phrase)
            if not key:
                continue
            pid = latin_map.get(key) or fr_map.get(key) or en_map.get(key)
            if pid:
                if pid not in matched_ids:
                    matched_ids.append(pid)
                for j in range(i, i + n):
                    consumed[j] = True

    return matched_ids


def parse_description_codes(
    description: str,
    station_map: dict,
    habitat_codes: dict,
    substrat_codes: dict,
    vegetation_map: dict = None,
    projet_map: dict = None,
    vegetation_code_map: dict = None,
    vegetation_fr_map: dict = None,
    vegetation_en_map: dict = None,
) -> dict:
    """
    Extrait les codes terrain depuis Description rapide selon la convention :

      #FSL01          → Station d'inventaire (+ projet déduit du préfixe alpha)
      #coll           → Fongarium (checkbox)
      !BOM            → Habitat général (via "Code terrain")
      $BMC            → Substrat (via "Code terrain")
      @BOJ            → Végétation (via code_plante)
      @@BOJ           → Hôte - substrat (via code_plante)
      #Acer_saccharum → Végétation (rétrocompat nom latin avec underscore)
      Bouleau jaune   → Végétation (texte libre — match exact contre nom fr/lat/en)

    Insensible à la casse pour les codes préfixés. Le texte libre est scanné
    en greedy longest-first jusqu'à 4 mots consécutifs.

    Retourne :
      {
        "station_code"           : str | None,
        "projet_page_id"         : str | None,
        "has_coll"               : bool,
        "habitat_page_ids"       : list[str],
        "substrat_page_ids"      : list[str],
        "vegetation_page_ids"    : list[str],
        "hote_substrat_page_ids" : list[str],
      }
    """
    result = {
        "station_code": None,
        "projet_page_id": None,
        "has_coll": False,
        "habitat_page_ids": [],
        "substrat_page_ids": [],
        "vegetation_page_ids": [],
        "hote_substrat_page_ids": [],
    }

    if not description:
        return result

    vegetation_code_map = vegetation_code_map or {}
    vegetation_fr_map = vegetation_fr_map or {}
    vegetation_en_map = vegetation_en_map or {}
    vegetation_map = vegetation_map or {}
    habitat_codes = habitat_codes or {}
    substrat_codes = substrat_codes or {}
    station_map = station_map or {}

    bare_tokens: list[str] = []

    for raw in description.split():
        if not raw:
            continue
        # @@CODE → Hôte - substrat (lookup via code_plante)
        if raw.startswith("@@"):
            code = _strip_punct(raw[2:]).upper()
            if code and code in vegetation_code_map:
                pid = vegetation_code_map[code]
                if pid not in result["hote_substrat_page_ids"]:
                    result["hote_substrat_page_ids"].append(pid)
            continue

        # @CODE → Végétation (lookup via code_plante)
        if raw.startswith("@"):
            code = _strip_punct(raw[1:]).upper()
            if code and code in vegetation_code_map:
                pid = vegetation_code_map[code]
                if pid not in result["vegetation_page_ids"]:
                    result["vegetation_page_ids"].append(pid)
            continue

        # !CODE → Habitat général
        if raw.startswith("!"):
            code = _strip_punct(raw[1:]).upper()
            if code and code in habitat_codes:
                pid = habitat_codes[code]
                if pid not in result["habitat_page_ids"]:
                    result["habitat_page_ids"].append(pid)
            continue

        # $CODE → Substrat
        if raw.startswith("$"):
            code = _strip_punct(raw[1:]).upper()
            if code and code in substrat_codes:
                pid = substrat_codes[code]
                if pid not in result["substrat_page_ids"]:
                    result["substrat_page_ids"].append(pid)
            continue

        # #XXX → Station, Fongarium ou (rétrocompat) Végétation par nom latin
        if raw.startswith("#"):
            code = _strip_punct(raw[1:]).upper()
            if not code:
                continue
            if code == "COLL":
                result["has_coll"] = True
            elif code in station_map:
                result["station_code"] = code
                result["projet_page_id"] = None
                if projet_map:
                    prefix = _extract_station_prefix(code)
                    if prefix and prefix in projet_map:
                        result["projet_page_id"] = projet_map[prefix]
            else:
                # Rétrocompat : #Acer_saccharum → match nom latin
                latin_key = code.replace("_", " ").lower()
                if latin_key in vegetation_map:
                    pid = vegetation_map[latin_key]
                    if pid not in result["vegetation_page_ids"]:
                        result["vegetation_page_ids"].append(pid)
            continue

        # Aucun préfixe → texte libre, candidat au matching de nom de plante
        cleaned = _strip_punct(raw)
        if cleaned:
            bare_tokens.append(cleaned)

    # Scan greedy du texte libre pour les noms de plantes (latin/fr/en)
    bare_matches = _scan_bare_plant_names(
        bare_tokens, vegetation_map, vegetation_fr_map, vegetation_en_map
    )
    for pid in bare_matches:
        if pid not in result["vegetation_page_ids"]:
            result["vegetation_page_ids"].append(pid)

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
    session: requests.Session | None = None,
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
    species_map         = maps.get("species_map", {})
    taxon_id_map        = maps.get("taxon_id_map", {})
    old_names_map       = maps.get("old_names_map", {})
    station_map         = maps.get("station_map", {})
    habitat_codes       = maps.get("habitat_codes", {})
    substrat_codes      = maps.get("substrat_codes", {})
    vegetation_map      = maps.get("vegetation_map", {})
    vegetation_code_map = maps.get("vegetation_code_map", {})
    vegetation_fr_map   = maps.get("vegetation_fr_map", {})
    vegetation_en_map   = maps.get("vegetation_en_map", {})
    projet_map          = maps.get("projet_map", {})

    parsed = parse_description_codes(
        description, station_map, habitat_codes, substrat_codes,
        vegetation_map, projet_map,
        vegetation_code_map, vegetation_fr_map, vegetation_en_map,
    )
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

    # Projet d'inventaire (déduit du préfixe de la station)
    if parsed.get("projet_page_id"):
        props[PROP_PROJET] = {"relation": [{"id": parsed["projet_page_id"]}]}
        prefix = _extract_station_prefix(parsed["station_code"]) if parsed["station_code"] else "?"
        log.append(f"Projet→{prefix}")

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

    # Végétation
    if parsed["vegetation_page_ids"]:
        props[PROP_VEGETATION] = {"relation": [{"id": vid} for vid in parsed["vegetation_page_ids"]]}
        log.append(f"Végétation→{len(parsed['vegetation_page_ids'])} liée(s)")

    # Hôte - substrat (préfixe @@CODE)
    if parsed["hote_substrat_page_ids"]:
        props[PROP_HOTE_SUBSTRAT] = {"relation": [{"id": hid} for hid in parsed["hote_substrat_page_ids"]]}
        log.append(f"Hôte-substrat→{len(parsed['hote_substrat_page_ids'])} lié(s)")

    if not props:
        return False, "Rien à résoudre"

    resp = _notion_patch_with_retry(token, page_id, props, session=session)
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
    success = 0
    skipped = 0
    errors  = []

    with requests.Session() as session:
        # Re-fetch pages using the session if we need to query the whole DB
        pages = _query_db_all(token, obs_db_id, session=session)

        if filter_unresolved:
            pages = [
                p for p in pages
                if not p["properties"].get(PROP_ESPECE, {}).get("relation")
            ]

        total = len(pages)
        for i, page in enumerate(pages):
            page_id = page["id"]
            props   = page["properties"]

            taxon_name = _get_title(props)
            desc_prop = props.get("Description rapide", {})
            description = _get_rich_text(desc_prop)
            taxon_id = extract_taxon_id_from_props(props)

            if not taxon_name:
                skipped += 1
                if progress_callback:
                    progress_callback(i + 1, total)
                continue

            try:
                ok, msg = resolve_and_update_relations(
                    page_id, taxon_name, description, maps, token, db_props_schema, 
                    taxon_id=taxon_id, session=session
                )
                if ok:
                    success += 1
                else:
                    if "HTTP" in msg:
                        errors.append(f"Page {page_id}: {msg}")
                    skipped += 1
            except Exception as e:
                errors.append(f"Page {page_id} (Exception): {e}")
                skipped += 1

            if progress_callback:
                progress_callback(i + 1, total)

    return {
        "success": success, 
        "skipped": skipped, 
        "errors": errors, 
        "total": success + skipped
    }
