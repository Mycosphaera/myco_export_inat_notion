"""Tests du routage vers le « s.l. » — purs, sans réseau (les appels Notion sont remplacés).

La règle (décision de Mathias du 2026-11-23, « par prudence on route vers le s.l. ») : une récolte qui tombe sur une
fiche « espèce vraie » — par son identifiant iNaturalist ou par son nom — va à la fiche « s.l. » vers laquelle pointe
la relation « Sens large » ; sans cette relation (ou sans la colonne), rien ne change. Ce que ces tests gardent fermé :
le routage vaut pour tous les niveaux de résolution, le chargement de la Mycoliste lit la relation (et charge tout
quand le schéma est illisible, plutôt que de perdre le routage en silence), et l'écriture de la relation « Espèce »
porte bien la fiche « s.l. ». Lance : `pytest test_routage_sens_large.py` OU `python test_routage_sens_large.py`.
"""

import enricher

STRICT, SL, AUTRE = "page-strict", "page-sl", "page-autre"
CARTE = {STRICT: SL}


def test_le_routage_vaut_par_l_identifiant():
    assert enricher.match_species("Scutellinia scutellata", {}, 49137, {49137: STRICT}, {}, CARTE) == SL


def test_le_routage_vaut_par_le_nom_et_par_l_ancien_nom():
    especes = {"scutellinia scutellata": STRICT}
    assert enricher.match_species("Scutellinia scutellata", especes, None, {}, {}, CARTE) == SL
    assert enricher.match_species("Scutellinia vetus", {}, None, {}, {"scutellinia vetus": STRICT}, CARTE) == SL
    assert enricher.match_species("Scutellinia cf. scutellata", especes, None, {}, {}, CARTE) == SL


def test_sans_relation_rien_ne_change():
    assert enricher.match_species("Amanita muscaria", {"amanita muscaria": AUTRE}, None, {}, {}, CARTE) == AUTRE
    assert enricher.match_species("Scutellinia scutellata", {"scutellinia scutellata": STRICT}, None, {}, {}, None) == STRICT
    assert enricher.match_species("Inconnue", {}, None, {}, {}, CARTE) is None


def test_la_relation_se_lit_et_une_double_cible_ne_route_pas():
    assert enricher.sens_large_de({"Sens large": {"relation": [{"id": SL}]}}) == SL
    assert enricher.sens_large_de({"Sens large": {"relation": [{"id": SL}, {"id": AUTRE}]}}) is None
    assert enricher.sens_large_de({"Sens large": {"relation": []}}) is None and enricher.sens_large_de({}) is None


def _charger(id_relation, pages):
    """`build_lookup_maps` avec la Mycoliste seule, Notion remplacé. → (cartes, filter_properties demandés)."""
    demandes = []
    gardes = (enricher._query_db_all, enricher._id_propriete_sens_large)
    enricher._id_propriete_sens_large = lambda token, db_id, session=None: id_relation
    enricher._query_db_all = lambda token, db_id, session=None, filter_properties=None: demandes.append(filter_properties) or pages
    try:
        return enricher.build_lookup_maps("jeton", {"mycoliste": "M"}), demandes
    finally:
        enricher._query_db_all, enricher._id_propriete_sens_large = gardes


PAGES = [
    {"id": STRICT, "properties": {"Nom latin": {"type": "title", "title": [{"plain_text": "Scutellinia scutellata"}]},
                                  "Inat Taxon ID": {"type": "number", "number": 49137},
                                  "Sens large": {"type": "relation", "relation": [{"id": SL}]}}},
    {"id": SL, "properties": {"Nom latin": {"type": "title", "title": [{"plain_text": "Scutellinia scutellata s.l."}]}}},
]


def test_le_chargement_lit_la_relation_et_la_demande_par_son_id():
    # Notion rend les identifiants de colonne DÉJÀ encodés (« NmF%3F » pour « Inat Taxon ID », mesuré le 2026-11-24) :
    # l'identifiant passe tel quel, jamais réencodé en « abc%253F » (revue CodeRabbit du 2026-11-24)
    cartes, demandes = _charger("abc%3F", PAGES)
    assert cartes["sens_large_map"] == {STRICT: SL}
    assert "abc%3F" in demandes[0] and "abc%253F" not in demandes[0], demandes


def test_un_schema_illisible_charge_tout_au_lieu_de_perdre_le_routage():
    cartes, demandes = _charger(enricher._SCHEMA_ILLISIBLE, PAGES)
    assert demandes[0] is None and cartes["sens_large_map"] == {STRICT: SL}


def test_sans_la_colonne_la_carte_est_vide():
    cartes, demandes = _charger(None, [PAGES[1]])
    assert cartes["sens_large_map"] == {} and demandes[0] == ["title", "NmF%3F", "%3C~w%5C"]


def test_la_relation_espece_ecrite_porte_la_fiche_sl():
    ecrit = {}

    class Rep:
        status_code, text = 200, ""

    gardee = enricher._notion_patch_with_retry
    enricher._notion_patch_with_retry = lambda token, page_id, props, session=None: ecrit.update(props) or Rep()
    try:
        cartes = {"species_map": {}, "taxon_id_map": {49137: STRICT}, "old_names_map": {}, "sens_large_map": CARTE}
        ok, _ = enricher.resolve_and_update_relations("obs-1", "Scutellinia scutellata", "", cartes, "jeton", taxon_id=49137)
    finally:
        enricher._notion_patch_with_retry = gardee
    assert ok and ecrit[enricher.PROP_ESPECE] == {"relation": [{"id": SL}]}, ecrit


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
