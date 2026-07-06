"""Tests de `enricher.parse_description_codes` — purs, sans réseau.

Verrouille surtout la règle « #coll ET *coll cochent Fongarium » (des membres
ont utilisé l'un ou l'autre). Lance : `pytest test_enricher_codes.py` OU
`python test_enricher_codes.py`.
"""

from enricher import parse_description_codes, lint_description_codes

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


# ── lint_description_codes : aperçu non destructif avant import ──────────────

# Maps avec noms lisibles (comme le vrai build_lookup_maps après l'ajout).
LINT_MAPS = {
    "station_map": {"FSL01": "pid_st"},
    "station_names": {"FSL01": "Forêt Seigneurie Lotbinière 01"},
    "habitat_codes": {"BOM": "pid_h"},
    "habitat_names": {"BOM": "Boisé mixte"},
    "substrat_codes": {"BMC": "pid_s"},
    "substrat_names": {"BMC": "Bois mort de conifère"},
    "vegetation_code_map": {"BOJ": "pid_v"},
    "vegetation_code_names": {"BOJ": "Betula alleghaniensis"},
    "vegetation_map": {"acer saccharum": "pid_acer"},
}


def test_lint_station_reconnue_avec_nom():
    r = lint_description_codes("*FSL01", LINT_MAPS)
    assert r["has_issues"] is False
    assert r["recognized"][0]["type"] == "station"
    assert r["recognized"][0]["name"] == "Forêt Seigneurie Lotbinière 01"
    assert not r["unrecognized"]


def test_lint_station_inconnue_signalee():
    r = lint_description_codes("*FSL99", LINT_MAPS)
    assert r["has_issues"] is True
    assert r["unrecognized"][0]["token"] == "*FSL99"
    assert r["unrecognized"][0]["type"] == "station"


def test_lint_coll_les_deux_prefixes():
    for tok in ("#coll", "*coll", "*COLL"):
        r = lint_description_codes(tok, LINT_MAPS)
        assert r["has_issues"] is False
        assert r["recognized"][0]["type"] == "fongarium"


def test_lint_arobase_signale():
    # @ = piège iNat (mention utilisateur) → doit être signalé.
    r = lint_description_codes("@mycosystema", LINT_MAPS)
    assert r["has_issues"] is True
    assert "@mycosystema" in r["at_warnings"]


def test_lint_habitat_substrat_inconnus():
    r = lint_description_codes("!XYZ $ZZZ", LINT_MAPS)
    types = {u["type"] for u in r["unrecognized"]}
    assert types == {"habitat", "substrat"}


def test_lint_texte_libre_ignore():
    # Prose descriptive normale → aucun code, aucun problème.
    r = lint_description_codes("Trouvé au sol près d'un vieux chêne", LINT_MAPS)
    assert r["has_issues"] is False
    assert not r["recognized"] and not r["unrecognized"]


def test_lint_combo_mixte():
    r = lint_description_codes("*FSL01 #coll $BMC !BADHAB", LINT_MAPS)
    assert r["has_issues"] is True  # !BADHAB inconnu
    ok_types = {x["type"] for x in r["recognized"]}
    assert {"station", "fongarium", "substrat"} <= ok_types
    assert r["unrecognized"][0]["token"] == "!BADHAB"


def test_lint_plante_reconnue():
    r = lint_description_codes("#BOJ", LINT_MAPS)
    assert r["has_issues"] is False
    assert r["recognized"][0]["type"] == "plante"
    assert r["recognized"][0]["name"] == "Betula alleghaniensis"


def test_lint_plante_inconnue():
    r = lint_description_codes("#ZZZ", LINT_MAPS)
    assert r["has_issues"] is True
    assert r["unrecognized"][0]["type"] == "plante"


def test_lint_hote_substrat_reconnu():
    r = lint_description_codes("##BOJ", LINT_MAPS)
    assert r["has_issues"] is False
    assert r["recognized"][0]["type"] == "hôte-substrat"
    assert r["recognized"][0]["name"] == "Betula alleghaniensis"


def test_lint_description_non_texte_ne_crashe_pas():
    # Robustesse : une Description non-textuelle (NaN pandas, None) ne doit pas
    # crasher lint_description_codes (retour d'un DataFrame → .split() sinon) et
    # doit court-circuiter proprement (aucun code ni avertissement).
    for _bad in (None, float("nan")):
        r = lint_description_codes(_bad, LINT_MAPS)
        assert r["has_issues"] is False
        assert r["recognized"] == []
        assert r["unrecognized"] == []
        assert r["at_warnings"] == []


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
