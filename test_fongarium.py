"""Tests de `fongarium.suggest_fongarium_prefix`.

Lance avec `pytest test_fongarium.py` OU `python test_fongarium.py`.
"""

from fongarium import suggest_fongarium_prefix


def test_initiales_simples():
    # Cas réels de la base (convention = initiales du nom).
    assert suggest_fongarium_prefix("François Guay") == "FG"
    assert suggest_fongarium_prefix("Gabriel Boilard") == "GB"
    assert suggest_fongarium_prefix("Katia Burelle") == "KB"


def test_trait_dunion_separe_les_mots():
    assert suggest_fongarium_prefix("Mathias Rocheleau-Duplain") == "MRD"
    assert suggest_fongarium_prefix("Jonathan Jensen-Lynch") == "JJL"


def test_accents_retires():
    assert suggest_fongarium_prefix("Étienne Doyon") == "ED"


def test_particules_ignorees():
    assert suggest_fongarium_prefix("Marie de la Tour") == "MT"


def test_nom_vide_ou_invalide():
    assert suggest_fongarium_prefix("") == ""
    assert suggest_fongarium_prefix(None) == ""
    assert suggest_fongarium_prefix("   ") == ""


def test_collision_etend_avec_lettres_du_dernier_mot():
    # 'François Guay' → base 'FG' déjà prise → étend avec la 2e lettre de 'Guay'.
    assert suggest_fongarium_prefix("François Guay", taken={"FG"}) == "FGU"
    # 'FG' et 'FGU' pris → 'FGA' (3e lettre).
    assert suggest_fongarium_prefix("François Guay", taken={"FG", "FGU"}) == "FGA"


def test_collision_insensible_a_la_casse():
    assert suggest_fongarium_prefix("Katia Burelle", taken={"kb"}) == "KBU"


def test_collision_suffixe_numerique_en_dernier_recours():
    # Extensions épuisées (base 'A', seule lettre suivante 'l' → 'AL' déjà pris)
    # → repli sur le suffixe numérique.
    assert suggest_fongarium_prefix("Al", taken={"A", "AL"}) == "A2"


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
