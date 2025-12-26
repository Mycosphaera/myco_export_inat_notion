import streamlit as st
from supabase import create_client

# --- SUPABASE CLIENT INITIALIZATION ---
try:
    if "supabase" in st.secrets:
        # Helper to find keys robustly
        def get_secret(section, possibilities):
            for k in possibilities:
                if k in st.secrets[section]: return st.secrets[section][k]
            return None
            
        supa_url = get_secret("supabase", ["url", "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"])
        supa_key = get_secret("supabase", ["key", "SUPABASE_KEY", "SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY"])
        
        if supa_url and supa_key:
            supabase = create_client(supa_url, supa_key)
        else:
            supabase = None
    else:
        supabase = None
except Exception as e:
    # Silent fail if not configured, or log error
    # print(f"Supabase Init Error: {e}") 
    supabase = None

def get_user_by_email(email):
    """
    Récupère un utilisateur par son email.
    Retourne le profil complet ou None.
    """
    if not supabase:
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
        print(f"Erreur DB: {e}")
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
        return False

# Anciennes fonctions gardées pour compatibilité ou log
def log_action(username, action, details=""):
    if not supabase: return
    # pass
