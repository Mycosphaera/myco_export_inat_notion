# -*- coding: utf-8 -*-
"""Signer la qualité d'un point importé d'iNaturalist — la règle, et rien d'autre.

🔴 **La provenance n'est pas la qualité.** « Ça vient d'iNaturalist » dit *d'où* ça vient, pas
*combien c'est fiable* : une même source porte le GPS de terrain et l'épingle traînée sur la
carte depuis le salon. Ce qui les distingue est déjà dans la donnée — le rayon en mètres.

Avant le 2026-09-13, cet importateur **n'écrivait pas du tout** `Type de coordonnées GPS`, et
le portail y mettait « GPS in situ » par défaut de paramètre. Mesuré sur les 9 593 observations
iNat de la base : **2 309 seulement le méritaient (24 %)**.

⚠️ Le même fichier faisait pourtant déjà ce raisonnement **pour Flickr** (`_is_gps_suspect`
dans `flickr_fetcher.py`, seuil sur `accuracy`). La voie iNaturalist était le seul angle mort.

🔴 **DUPLIQUÉ À DESSEIN.** La règle vit aussi dans
`portail-myco-reflex/repo/portail_myco/lib/new_observation.py`. Trois dépôts écrivent dans la
même base et aucun ne peut importer les autres ; les copies portent donc le **même jeu de cas
de référence**, et `verifier_cas_de_reference()` tombe si l'une dérive. Une divergence se voit
au lieu de vivre.
"""
from __future__ import annotations

GPS_IN_SITU = "GPS in situ"
GPS_DECLAREES = "Coordonnées déclarées"
GPS_CENTROIDE = "Centroïde"
GPS_TOPONYME = "Géocodage à toponyme"
GPS_INDISPONIBLE = "Non disponible"
GPS_OBSCURCIE = "Obscurcie (iNaturalist)"

SEUIL_IN_SITU_M = 50       # au-delà, un téléphone décrit une zone, plus un point
SEUIL_DECLAREES_M = 250    # borne haute d'un point placé à la main sur une carte
SEUIL_CENTROIDE_M = 5000   # la valeur poussée vers iNat pour un toponyme


def rayon_public_inat(obs: dict) -> int | None:
    """Le rayon qui décrit vraiment les coordonnées PUBLIQUES.

    🔴 `public_positional_accuracy`, jamais `positional_accuracy`. Une observation
    obscurcie déclare `positional_accuracy = 1 m` — la précision du relevé d'origine, que
    personne ne voit — pendant que son point public fait 27 190 m. Lire le mauvais champ
    plante un point brouillé de 27 km comme un relevé de terrain.
    """
    v = obs.get("public_positional_accuracy")
    return v if v is not None else obs.get("positional_accuracy")


def coord_type_depuis_inat(obs: dict) -> tuple[str, int | None]:
    """(type de coordonnées, rayon en mètres) déduits d'une observation iNaturalist.

    Le rayon rendu vaut `None` quand il est inconnu — ⛔ **jamais 0**. Zéro voudrait dire
    « parfaitement précis » et ferait des 1 996 inconnues les lignes les plus fiables de la
    base.
    """
    r = rayon_public_inat(obs)
    if obs.get("obscured") or obs.get("geoprivacy") == "obscured":
        return GPS_OBSCURCIE, r
    if r is None:
        return GPS_INDISPONIBLE, None
    if r <= SEUIL_IN_SITU_M:
        return GPS_IN_SITU, r
    if r <= SEUIL_DECLAREES_M:
        return GPS_DECLAREES, r
    if r <= SEUIL_CENTROIDE_M:
        return GPS_CENTROIDE, r
    return GPS_TOPONYME, r


# ⚠️ IDENTIQUE, au caractère près, à `CAS_DE_REFERENCE` du portail.
CAS_DE_REFERENCE = [
    ({"public_positional_accuracy": 4}, GPS_IN_SITU, 4),
    ({"public_positional_accuracy": 50}, GPS_IN_SITU, 50),
    ({"public_positional_accuracy": 51}, GPS_DECLAREES, 51),
    ({"public_positional_accuracy": 250}, GPS_DECLAREES, 250),
    ({"public_positional_accuracy": 251}, GPS_CENTROIDE, 251),
    ({"public_positional_accuracy": 5000}, GPS_CENTROIDE, 5000),
    ({"public_positional_accuracy": 5001}, GPS_TOPONYME, 5001),
    ({}, GPS_INDISPONIBLE, None),
    ({"positional_accuracy": None}, GPS_INDISPONIBLE, None),
    ({"positional_accuracy": 1, "public_positional_accuracy": 27190,
      "obscured": True}, GPS_OBSCURCIE, 27190),
    ({"positional_accuracy": 5, "geoprivacy": "obscured",
      "public_positional_accuracy": 27063}, GPS_OBSCURCIE, 27063),
    ({"positional_accuracy": 12}, GPS_IN_SITU, 12),
]


def verifier_cas_de_reference() -> list[str]:
    """Rend la liste des écarts. Vide = la règle est celle qu'on croit."""
    ecarts = []
    for obs, type_attendu, rayon_attendu in CAS_DE_REFERENCE:
        t, r = coord_type_depuis_inat(obs)
        if (t, r) != (type_attendu, rayon_attendu):
            ecarts.append(f"{obs} → ({t}, {r}) au lieu de ({type_attendu}, {rayon_attendu})")
    return ecarts


def proprietes_notion(obs: dict, schema: dict) -> dict:
    """Le fragment de `properties` à fusionner dans la page Notion.

    Rend un dict vide si la base n'a pas les colonnes : mieux vaut ne rien écrire que
    faire échouer la création de la page — et Notion fabriquerait une option en double si
    on lui envoyait une valeur pour un select absent.
    """
    type_final, rayon = coord_type_depuis_inat(obs)
    props: dict = {}
    col_type = "Type de coordonnées GPS"
    if col_type in schema and schema[col_type].get("type") == "select":
        options = {o["name"] for o in schema[col_type]["select"]["options"]}
        # ⛔ N'écrire QUE ce que le select connaît déjà. Un nom inconnu crée une option —
        # c'est ainsi qu'est apparu « Géocodage — toponyme » à côté de « Géocodage à toponyme ».
        if type_final in options:
            props[col_type] = {"select": {"name": type_final}}
    col_rayon = "Rayon (m)"
    if rayon is not None and col_rayon in schema and schema[col_rayon].get("type") == "number":
        props[col_rayon] = {"number": int(rayon)}
    return props


if __name__ == "__main__":
    # La console Windows est en cp1252 : sans ceci, un emoji fait planter le test
    # lui-meme et le code de sortie ment sur son resultat.
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ec = verifier_cas_de_reference()
    print(f"{len(CAS_DE_REFERENCE)} cas de référence · {len(ec)} écart(s)")
    for e in ec:
        print("   🔴", e)
    print("✅ la règle est celle qu'on croit" if not ec else "🔴 la règle a dérivé")
    sys.exit(0 if not ec else 2)
