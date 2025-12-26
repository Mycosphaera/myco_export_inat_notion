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

def check_credentials(username, password):
    """
    Vérifie si le nom d'utilisateur et le mot de passe correspondent.
    Retourne True si c'est bon, False sinon.
    """
    if not supabase:
        return False

    try:
        # On cherche une ligne qui a EXACTEMENT ce nom et ce mot de passe
        response = supabase.table("user_profiles")\
            .select("*")\
            .eq("auth_username", username)\
            .eq("password", password)\
            .execute()
        
        # Si la liste 'data' n'est pas vide, c'est que l'utilisateur existe
        if response.data and len(response.data) > 0:
            return True
        else:
            return False
    except Exception as e:
        print(f"Erreur de connexion : {e}")
        return False

def get_user_profile(username):
    """
    Récupère les infos du profil (ex: lien Notion)
    """
    if not supabase:
        return None
    try:
        response = supabase.table("user_profiles").select("*").eq("auth_username", username).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception:
        return None

def log_action(username, action, details=""):
    """
    Log une action utilisateur (placeholder pour le moment)
    """
    if not supabase:
        return
    # print(f"[LOG] {username}: {action} - {details}")
    # Plus tard, on pourra écrire dans une table 'logs'
    pass
