import streamlit as st
from supabase import create_client

# --- SUPABASE CLIENT INITIALIZATION ---
try:
    # Helper to find keys in a section OR at root (for Streamlit Cloud compatibility)
    def find_key(possible_names, section="supabase"):
        # 1. Try Section
        if section in st.secrets:
            for k in possible_names:
                if k in st.secrets[section]: return st.secrets[section][k]
        
        # 2. Try Root
        for k in possible_names:
            if k in st.secrets: return st.secrets[k]
        
        return None

    supa_url = find_key(["url", "URL", "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"])
    supa_key = find_key(["key", "KEY", "SUPABASE_KEY", "SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY"])
    
    if supa_url and supa_key:
        supabase = create_client(supa_url, supa_key)
    else:
        # print("Supabase keys not found.")
        supabase = None

except Exception as e:
    # Silent fail if not configured, or log error
    print(f"Supabase Init Error: {e}") 
    supabase = None

def _is_missing_column_error(e, column: str) -> bool:
    """True si l'exception Supabase/PostgREST signale que `column` est absente
    de la table (schema cache). On teste d'abord le code structuré PostgREST
    (`PGRST204` = colonne introuvable) ; repli sur le texte du message sinon.
    """
    msg = str(e).lower()
    code = str(getattr(e, "code", "") or "")
    col = column.lower()
    if code == "PGRST204" and col in msg:
        return True
    return col in msg and (
        "column" in msg or "does not exist" in msg or "schema cache" in msg
    )


def get_user_by_email(email):
    """
    Récupère un utilisateur par son email.
    Retourne le profil complet ou None.
    """
    if not supabase:
        print("❌ Supabase client NOT initialized in get_user_by_email")
        return None
    try:
        # On suppose que la colonne s'appelle 'email' ou qu'on utilise 'auth_username' comme email
        # Adaptez le nom de la colonne si besoin (dans Supabase, souvent 'email' ou 'auth_username')
        response = supabase.table("user_profiles").select("*").eq("auth_username", email).execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        else:
            return None
    except Exception as e:
        print(f"Erreur DB (get_user): {e}")
        return None

def create_user_profile(email, notion_name, inat_username, notion_portail_page_id=None, inat_user_id=None):
    """
    Crée un nouveau profil utilisateur.

    Args:
        email: identifiant unique (email)
        notion_name: nom affiché dans la colonne Mycologue (select) de la BD Observations
        inat_username: login iNaturalist
        notion_portail_page_id: ID Notion de la page Portail du mycologue de l'utilisateur
            (utilisé pour remplir la colonne `Mycologue (relation)` à l'import).
            Obligatoire pour les nouveaux signups, mais accepté comme None pour
            les chemins de code legacy ou les tests.
        inat_user_id: ID numérique iNaturalist (str) — ancre de recherche robuste
            (jamais de 422). Optionnel ; ignoré proprement si la colonne
            `inat_user_id` n'a pas encore été ajoutée à la table (migration).
    """
    if not supabase:
        return False

    new_user = {
        "auth_username": email,       # On utilise l'email comme identifiant unique
        "notion_user_name": notion_name, # CORRECTION: Nom de colonne réel
        "inat_username": inat_username,
        "password": "NO_PASSWORD"     # Champ technique rempli par défaut
    }
    if notion_portail_page_id:
        new_user["notion_portail_page_id"] = notion_portail_page_id
    if inat_user_id:
        new_user["inat_user_id"] = str(inat_user_id)

    try:
        response = supabase.table("user_profiles").insert(new_user).execute()
        # Vérification loose car l'API change parfois
        if response.data:
            return True
        return True # Si pas d'exception, on suppose que ça a marché (API v2 retourne parfois data=[...])
    except Exception as e:
        err_msg = str(e).lower()
        # Colonne `inat_user_id` pas encore migrée → on réessaie SANS, pour ne
        # jamais bloquer la création de compte (l'ALTER TABLE peut suivre).
        if "inat_user_id" in new_user and _is_missing_column_error(e, "inat_user_id"):
            new_user.pop("inat_user_id", None)
            try:
                supabase.table("user_profiles").insert(new_user).execute()
                return True
            except Exception as e2:
                e, err_msg = e2, str(e2).lower()
        print(f"Erreur Création Profil: {e}")
        # Detect Duplicate Key Error (Postgres Code 23505)
        # Supabase-py often matches strings in message
        if "duplicate key" in err_msg or "unique constraint" in err_msg:
             st.error("⚠️ Ce compte existe déjà ! Essayez de vous connecter.")
             return False

        st.error(f"Erreur technique: {e}")
        return False

# Anciennes fonctions gardées pour compatibilité ou log
def log_action(username, action, details=""):
    if not supabase: return
    # pass

def update_user_profile(user_id, updates):
    """
    Updates the user profile in Supabase.
    :param user_id: UUID of the user from 'user_profiles' table (not auth).
    :param updates: Dictionary of columns to update.
    :return: True if success, Error message (str) if fail.
    """
    if not supabase:
        return "Erreur de connexion Supabase."

    try:
        supabase.table("user_profiles").update(updates).eq("id", user_id).execute()
        return True
    except Exception as e:
        # Colonne `inat_user_id` pas encore migrée → réessaie SANS, pour ne pas
        # bloquer la sauvegarde des autres champs (l'ALTER TABLE peut suivre).
        if "inat_user_id" in updates and _is_missing_column_error(e, "inat_user_id"):
            reduced = {k: v for k, v in updates.items() if k != "inat_user_id"}
            try:
                supabase.table("user_profiles").update(reduced).eq("id", user_id).execute()
                return True
            except Exception as e2:
                return f"Erreur lors de la mise à jour: {e2}"
        return f"Erreur lors de la mise à jour: {e}"


def get_taken_fongarium_prefixes(exclude_user_id=None):
    """Ensemble (MAJUSCULES) des préfixes Fongarium déjà utilisés par d'AUTRES
    utilisateurs — sert à empêcher les collisions. `exclude_user_id` = l'id du
    profil courant (on ne se compte pas soi-même). En cas d'erreur de lecture,
    renvoie un ensemble vide (on ne bloque personne sur une panne).
    """
    if not supabase:
        return set()
    try:
        resp = supabase.table("user_profiles").select("id, fongarium_prefix").execute()
        taken = set()
        for row in (resp.data or []):
            if exclude_user_id is not None and row.get("id") == exclude_user_id:
                continue
            pfx = (row.get("fongarium_prefix") or "").strip().upper()
            if pfx:
                taken.add(pfx)
        return taken
    except Exception as e:
        print(f"Erreur get_taken_fongarium_prefixes: {e}")
        return set()
