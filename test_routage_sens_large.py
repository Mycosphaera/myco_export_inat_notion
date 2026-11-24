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


def _charger(schema, pages):
    """`build_lookup_maps` avec la Mycoliste seule, Notion remplacé. → (cartes, filter_properties demandés)."""
    demandes = []
    gardes = (enricher._query_db_all, enricher._schema_mycoliste)
    enricher._schema_mycoliste = lambda token, db_id, session=None: schema
    enricher._query_db_all = lambda token, db_id, session=None, filter_properties=None: demandes.append(filter_properties) or pages
    try:
        return enricher.build_lookup_maps("jeton", {"mycoliste": "M"}), demandes
    finally:
        enricher._query_db_all, enricher._schema_mycoliste = gardes


SCHEMA = {"Sens large": {"id": "mJkf", "type": "relation"}, "Statut nomenclatural": {"id": "st%3A", "type": "select"}}


def _page(pid, titre, sens_large=(), statut=None, nom_colonne="Sens large"):
    props = {"Nom latin": {"id": "title", "type": "title", "title": [{"plain_text": titre}]}}
    if sens_large:
        props[nom_colonne] = {"id": "mJkf", "type": "relation", "relation": [{"id": c} for c in sens_large]}
    if statut:
        props["Statut nomenclatural"] = {"id": "st%3A", "type": "select", "select": {"name": statut}}
    return {"id": pid, "properties": props}


PAGES = [_page(STRICT, "Scutellinia scutellata", [SL]), _page(SL, "Scutellinia scutellata s.l.")]


def test_le_chargement_demande_la_relation_par_son_id_tel_quel():
    # Notion rend les identifiants DÉJÀ encodés (« NmF%3F », mesuré le 2026-11-24) : passés tels quels, jamais réencodés
    cartes, demandes = _charger({**SCHEMA, "Statut nomenclatural": {"id": "st%3A"}}, PAGES)
    assert cartes["sens_large_map"] == {STRICT: SL}
    assert "mJkf" in demandes[0] and "st%3A" in demandes[0] and "st%253A" not in demandes[0], demandes


def test_une_colonne_renommee_route_encore():
    # rename-proof (AGENTS.md § 7.2 du portail) : la colonne se retrouve par son identifiant, pas par son nom
    schema = {"Sens large (s.l.)": {"id": "mJkf", "type": "relation"}}
    pages = [_page(STRICT, "Scutellinia scutellata", [SL], nom_colonne="Sens large (s.l.)"), _page(SL, "S. s.l.")]
    cartes, demandes = _charger(schema, pages)
    assert cartes["sens_large_map"] == {STRICT: SL} and "mJkf" in demandes[0]


def test_un_schema_illisible_charge_tout_et_le_dit():
    cartes, demandes = _charger(enricher._SCHEMA_ILLISIBLE, PAGES)
    assert demandes[0] is None and cartes["sens_large_map"] == {STRICT: SL}
    assert any("schéma illisible" in e for e in cartes["_errors"])


def test_sans_la_colonne_la_carte_est_vide():
    cartes, demandes = _charger({}, [PAGES[1]])
    assert cartes["sens_large_map"] == {} and demandes[0] == ["title", "NmF%3F", "%3C~w%5C"]


def test_une_cible_morte_ou_double_ne_route_pas_et_le_dit():
    pages = [_page(STRICT, "Scutellinia scutellata", [SL]), _page(SL, "S. s.l. (fusionnée)", statut="Ancien nom"),
             _page("p-double", "Xus yus", [SL, "p-autre-sl"]), _page("p-orpheline", "Xus zus", ["page-archivee"]),
             _page("p-autre-sl", "Xus s.l.")]
    cartes, _ = _charger(SCHEMA, pages)
    assert cartes["sens_large_map"] == {}, cartes["sens_large_map"]
    avert = " ".join(cartes["_errors"])
    assert "p-double" in avert and "page-archivee" in avert and SL in avert


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


def _resoudre(espece_actuelle):
    """`resolve_and_update_relations` d'une récolte de l'espèce 49137, Notion remplacé. → la relation « Espèce » écrite."""
    ecrit = {}

    class Rep:
        status_code, text = 200, ""

    gardee = enricher._notion_patch_with_retry
    enricher._notion_patch_with_retry = lambda token, page_id, props, session=None: ecrit.update(props) or Rep()
    try:
        cartes = {"species_map": {}, "taxon_id_map": {49137: STRICT}, "old_names_map": {}, "sens_large_map": CARTE}
        enricher.resolve_and_update_relations("obs-1", "Scutellinia scutellata", "", cartes, "jeton", taxon_id=49137,
                                              espece_actuelle=espece_actuelle)
    finally:
        enricher._notion_patch_with_retry = gardee
    return ecrit[enricher.PROP_ESPECE]["relation"][0]["id"]


def test_le_mode_force_ne_renvoie_pas_au_sl_une_recolte_deja_sur_la_fiche_espece():
    # revue CodeRabbit du 2026-11-24 : une récolte déplacée sur la fiche espèce par une preuve ADN y reste
    assert _resoudre([STRICT]) == STRICT
    assert _resoudre([]) == SL and _resoudre(None) == SL and _resoudre([AUTRE]) == SL


def test_l_adresse_envoyee_porte_les_identifiants_tels_quels():
    # revue CodeRabbit du 2026-11-24 : vérifier l'adresse réellement envoyée, pas seulement la liste demandée
    adresses = []

    class Rep:
        status_code = 200

        def json(self):
            return {"results": [], "has_more": False}

        def raise_for_status(self):
            pass

    class Session:
        def post(self, url, *a, **k):
            adresses.append(url)
            return Rep()

    enricher._query_db_all("jeton", "M", session=Session(), filter_properties=["title", "NmF%3F", "mJkf", "II~F"])
    assert "filter_properties=NmF%3F" in adresses[0] and "filter_properties=mJkf" in adresses[0]
    assert "%253F" not in adresses[0], adresses[0]


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
