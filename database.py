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
        print(f"🔍 Searching user: {email}")
        response = supabase.table("user_profiles").select("*").eq("auth_username", email).execute()
        
        if response.data and len(response.data) > 0:
            print(f"✅ User found: {response.data[0]['auth_username']}")
            return response.data[0]
        else:
            print("❌ User not found in DB request.")
            return None
    except Exception as e:
        print(f"Erreur DB (get_user): {e}")
        return None

def create_user_profile(email, notion_name, inat_username):
    """
    Crée un nouveau profil utilisateur.
    """
    if not supabase:
        return False
    
    new_user = {
        "auth_username": email,       # On utilise l'email comme identifiant unique
        "notion_user_name": notion_name, # CORRECTION: Nom de colonne réel
        "inat_username": inat_username,
        "password": "NO_PASSWORD"     # Champ technique rempli par défaut
    }
    
    try:
        response = supabase.table("user_profiles").insert(new_user).execute()
        # Vérification loose car l'API change parfois
        if response.data: 
            return True
        return True # Si pas d'exception, on suppose que ça a marché (API v2 retourne parfois data=[...])
    except Exception as e:
        print(f"Erreur Création Profil: {e}")
        # Detect Duplicate Key Error (Postgres Code 23505)
        # Supabase-py often matches strings in message
        err_msg = str(e).lower()
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
        response = supabase.table("user_profiles").update(updates).eq("id", user_id).execute()
        return True
    except Exception as e:
        return f"Erreur lors de la mise à jour: {e}"
