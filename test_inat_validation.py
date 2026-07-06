"""Tests de `inat_validation` — sans réseau (session iNat simulée).

Lance avec `pytest test_inat_validation.py` OU directement `python test_inat_validation.py`.
"""

from inat_validation import validate_inat_username, looks_like_invalid_inat_username


# ── Doublures de test (pas d'appel réseau réel) ──────────────────────────────

class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} Client Error")

    def json(self):
        return self._payload


class _FakeSession:
    """Renvoie une liste de logins fixe ; enregistre si .get a été appelé."""
    def __init__(self, logins):
        self._logins = logins
        self.called = False

    def get(self, *args, **kwargs):
        self.called = True
        return _FakeResp({"results": [{"login": l} for l in self._logins]})


class _BoomSession:
    """Simule une panne réseau."""
    def get(self, *args, **kwargs):
        raise ConnectionError("réseau coupé")


# ── looks_like_invalid_inat_username (heuristique sans réseau) ────────────────

def test_heuristique_flag_vide_courriel_espace():
    assert looks_like_invalid_inat_username("") is True
    assert looks_like_invalid_inat_username("   ") is True
    assert looks_like_invalid_inat_username(None) is True
    assert looks_like_invalid_inat_username("mboisaves@videotron.ca") is True
    assert looks_like_invalid_inat_username("jean dupont") is True


def test_heuristique_accepte_login_normal():
    assert looks_like_invalid_inat_username("mycosystema") is False
    assert looks_like_invalid_inat_username("marc_bois") is False


# ── validate_inat_username ───────────────────────────────────────────────────

def test_vide_rejete_sans_reseau():
    sess = _FakeSession([])
    login, err = validate_inat_username("", session=sess)
    assert login is None and err
    assert sess.called is False  # court-circuit avant l'API


def test_courriel_rejete_sans_reseau():
    # Le cas EXACT de Marc Bois : un courriel ne doit jamais atteindre l'API.
    sess = _FakeSession(["mboisaves"])
    login, err = validate_inat_username("mboisaves@videotron.ca", session=sess)
    assert login is None
    assert "courriel" in err.lower()
    assert sess.called is False


def test_login_valide_retourne_casse_officielle():
    # iNat renvoie la casse canonique ; on doit la retenir, pas celle tapée.
    sess = _FakeSession(["MycoSystema", "autre_user"])
    login, err = validate_inat_username("mycosystema", session=sess)
    assert err is None
    assert login == "MycoSystema"
    assert sess.called is True


def test_login_inexistant_rejete():
    sess = _FakeSession(["quelqun_dautre"])
    login, err = validate_inat_username("pseudo_bidon", session=sess)
    assert login is None
    assert "introuvable" in err.lower()


def test_panne_reseau_ne_leve_pas():
    login, err = validate_inat_username("mycosystema", session=_BoomSession())
    assert login is None
    assert err  # message dégradé, pas d'exception


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
