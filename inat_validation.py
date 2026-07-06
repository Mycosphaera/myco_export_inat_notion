"""Validation des pseudos (logins) iNaturalist.

Module volontairement SANS dépendance Streamlit pour rester testable en
isolation (`test_inat_validation.py`). On y centralise la vérification d'un
nom d'utilisateur iNaturalist, utilisée à 3 endroits de `app.py` :

  1. Inscription (« Créer mon portail »)
  2. Édition du profil (« Mon Profil »)
  3. Bouton « ➕ Ajouter un utilisateur » du tableau de bord

Contexte : l'API iNaturalist `/v1/observations` répond **422 Unprocessable
Entity** quand `user_id` n'est pas un login (ou un id numérique) valide — par
exemple un courriel. Or les anciens écrans stockaient le pseudo sans le
vérifier : un utilisateur qui tapait son courriel cassait *toutes* ses
recherches avec une erreur 422 cryptique. On valide donc à la source.
"""

from __future__ import annotations

import requests

_INAT_AUTOCOMPLETE_URL = "https://api.inaturalist.org/v1/users/autocomplete"
_USER_AGENT = "MycosphaeraPortail/1.2 (info@mycosphaera.com)"
_HELP_PSEUDO = (
    "C'est le nom affiché dans l'URL de ton profil iNaturalist : "
    "inaturalist.org/people/TON-PSEUDO — pas ton courriel ni ton nom complet."
)


def resolve_search_user_id(inat_user_id, inat_login: str | None) -> str:
    """Identifiant à passer à l'API iNat comme `user_id` de recherche.

    Priorité à l'**ID NUMÉRIQUE** (`inat_user_id`) : un id numérique ne renvoie
    jamais 422, contrairement à un login mal formé (courriel, typo). Repli sur le
    `login` sinon. Retourne "" si aucun des deux n'est exploitable.
    """
    uid = ("" if inat_user_id is None else str(inat_user_id)).strip()
    if uid.isdigit():
        return uid
    return (inat_login or "").strip()


def looks_like_invalid_inat_username(username: str | None) -> bool:
    """Heuristique RAPIDE et SANS réseau pour le bandeau d'alerte du dashboard.

    Renvoie ``True`` si le pseudo est manifestement cassé — vide, ressemblant à
    un courriel (``@``) ou contenant une espace. Les logins iNaturalist réels
    n'ont jamais ces caractères, donc aucun faux positif en pratique. Ne
    remplace PAS `validate_inat_username` (qui, elle, confirme l'existence via
    l'API) ; sert juste à signaler visuellement un profil à corriger.
    """
    u = (username or "").strip()
    return (not u) or ("@" in u) or any(c.isspace() for c in u)


def validate_inat_username(username: str | None, *, session=None, timeout: float = 10.0):
    """Vérifie un pseudo iNaturalist contre l'API publique `users/autocomplete`.

    Args:
        username: le pseudo saisi par l'utilisateur.
        session: objet exposant `.get(...)` (pour les tests) ; défaut = `requests`.
        timeout: délai max de la requête HTTP.

    Returns:
        ``(login_canonique, None)`` si le pseudo existe sur iNaturalist — on
        renvoie la casse OFFICIELLE renvoyée par iNat, pas celle tapée.
        ``(None, message_fr)`` sinon (vide, courriel, introuvable, ou panne
        réseau). La fonction **ne lève jamais** : l'appelant décide quoi faire
        du message (bloquer l'inscription, afficher une erreur, etc.).
    """
    candidate = (username or "").strip()

    if not candidate:
        return None, f"Le pseudo iNaturalist est vide. {_HELP_PSEUDO}"

    # Garde-fou immédiat : un courriel n'est jamais un login iNat valide.
    # On l'attrape avant l'appel réseau pour un message clair et instantané.
    if "@" in candidate:
        return None, (
            f"« {candidate} » ressemble à un courriel, pas à un pseudo "
            f"iNaturalist. {_HELP_PSEUDO}"
        )

    getter = (session or requests).get
    try:
        resp = getter(
            _INAT_AUTOCOMPLETE_URL,
            # Fenêtre large : l'autocomplete classe par pertinence ; on l'élargit
            # pour ne pas rater le match EXACT si des logins proches sont mieux
            # classés (cf. revue CodeRabbit PR #29).
            params={"q": candidate, "per_page": 30},
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        resp.raise_for_status()
        results = resp.json().get("results", []) or []
    except Exception as e:  # réseau, timeout, JSON, HTTP ≠ 200…
        return None, (
            "Impossible de vérifier le pseudo iNaturalist pour l'instant "
            f"(réseau ou API indisponible) : {e}"
        )

    # Match strict insensible à la casse → on retient la casse officielle d'iNat.
    for u in results:
        login = u.get("login") or ""
        if login.lower() == candidate.lower():
            return login, None

    return None, (
        f"Le pseudo iNaturalist « {candidate} » est introuvable. Vérifie "
        f"l'orthographe. {_HELP_PSEUDO}"
    )
