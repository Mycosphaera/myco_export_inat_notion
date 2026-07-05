"""Tests de `enricher.parse_description_codes` — purs, sans réseau.

Verrouille surtout la règle « #coll ET *coll cochent Fongarium » (des membres
ont utilisé l'un ou l'autre). Lance : `pytest test_enricher_codes.py` OU
`python test_enricher_codes.py`.
"""

from enricher import parse_description_codes

# Maps de test minimales (pas d'appel Notion).
STATIONS = {"FSL01": "pid_station_fsl01"}
PROJETS = {"FSL": "pid_projet_fsl"}
HABITATS = {"BOM": "pid_hab_bom"}
SUBSTRATS = {"BMC": "pid_sub_bmc"}


def _parse(desc):
    return parse_description_codes(
        desc, STATIONS, HABITATS, SUBSTRATS, projet_map=PROJETS
    )


# ── Fongarium : les deux préfixes ────────────────────────────────────────────

def test_coll_avec_diese():
    assert _parse("#coll").get("has_coll") is True


def test_coll_avec_asterisque():
    # La demande de Mathias : *coll doit AUSSI cocher Fongarium.
    assert _parse("*coll").get("has_coll") is True


def test_coll_insensible_casse():
    assert _parse("*COLL").get("has_coll") is True
    assert _parse("#Coll").get("has_coll") is True


def test_coll_star_ne_devient_pas_station():
    # *coll ne doit pas être interprété comme un code de station.
    r = _parse("*coll")
    assert r.get("station_code") is None


def test_pas_de_coll_par_defaut():
    assert _parse("*FSL01 $BMC").get("has_coll") is False


# ── Non-régression : le reste de la convention marche toujours ───────────────

def test_station_et_projet_deduit():
    r = _parse("*FSL01")
    assert r.get("station_code") == "FSL01"
    assert r.get("projet_page_id") == "pid_projet_fsl"
    assert r.get("has_coll") is False


def test_combo_realiste():
    # Une note terrain typique : station + collection + substrat.
    r = _parse("*FSL01 #coll $BMC !BOM")
    assert r.get("station_code") == "FSL01"
    assert r.get("has_coll") is True
    assert "pid_sub_bmc" in r.get("substrat_page_ids", [])
    assert "pid_hab_bom" in r.get("habitat_page_ids", [])


# ── Runner autonome (sans pytest) ────────────────────────────────────────────

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"  [OK]   {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  [FAIL] {t.__name__} -- {e!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} tests OK")
    raise SystemExit(1 if failures else 0)
