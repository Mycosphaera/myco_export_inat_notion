"""Aide au préfixe Fongarium (sans dépendance Streamlit → testable).

Le préfixe Fongarium namespace les numéros de spécimen d'un membre (MRD0001,
MRD0002…). Convention observée dans la base : ce sont les **initiales du nom**
(ex. « Mathias Rocheleau-Duplain » → MRD, « François Guay » → FG, « Jonathan
Jensen-Lynch » → JJL ; les traits d'union séparent des mots). Il doit être
**unique** entre membres (sinon deux spécimens partageraient le même identifiant).
"""

from __future__ import annotations

import re
import unicodedata

# Particules qu'on ne compte pas dans les initiales (noms composés français).
_PARTICLES = {"de", "du", "des", "la", "le", "les", "van", "von", "der", "den", "d", "l"}


def _name_words(name: str | None) -> list[str]:
    """Mots significatifs d'un nom : accents retirés, découpe sur espaces / traits
    d'union / apostrophes / points, particules écartées (mais on garde tout si le
    filtrage vide la liste).
    """
    if not name:
        return []
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    raw = [w for w in re.split(r"[\s\-'’.]+", n) if w and w[0].isalpha()]
    filtered = [w for w in raw if w.lower() not in _PARTICLES]
    return filtered or raw


def suggest_fongarium_prefix(name: str | None, taken=None) -> str:
    """Suggère un préfixe = INITIALES de chaque mot du nom, en MAJUSCULES et sans
    accents. Ex. « Mathias Rocheleau-Duplain » → ``MRD``, « François Guay » → ``FG``.

    Si ``taken`` (itérable de préfixes déjà pris) est fourni et que la base entre
    en collision, on l'ÉTEND — lettres suivantes du dernier mot, puis suffixe
    numérique — jusqu'à un préfixe libre. Retourne ``""`` si le nom est inexploitable.
    """
    taken_up = {(p or "").strip().upper() for p in (taken or [])}
    taken_up.discard("")

    words = _name_words(name)
    if not words:
        return ""
    base = "".join(w[0] for w in words).upper()[:4]
    if not base:
        return ""
    if base not in taken_up:
        return base

    # Collision → base + UNE lettre suivante du dernier mot (FG → FGU, FGA…).
    for extra in words[-1][1:]:
        cand = (base + extra).upper()[:6]
        if cand not in taken_up:
            return cand
    # Dernier recours : suffixe numérique.
    for i in range(2, 100):
        c = f"{base}{i}"
        if c not in taken_up:
            return c
    return base
