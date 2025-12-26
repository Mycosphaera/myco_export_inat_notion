import streamlit as st
from supabase import create_client

st.title("Test de connexion Supabase")

# 1. Initialisation
try:
    # Helper pour trouver les clés peu importe leur nom (url, SUPABASE_URL, etc.)
    def get_secret(section, possibilities):
        for key in possibilities:
            if key in st.secrets[section]:
                return st.secrets[section][key]
        return None

    url = get_secret("supabase", ["url", "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"])
    key = get_secret("supabase", ["key", "SUPABASE_KEY", "SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY"])
    
    if not url or not key:
        st.error("❌ Impossible de trouver l'URL ou la Clé Supabase dans secrets.toml. Vérifiez les noms.")
        st.stop()
        
    st.info(f"🔍 URL lue par Python : '{url}'") # Debug URL
    
    supabase = create_client(url, key)
    st.success("✅ Client Supabase initialisé !")
except Exception as e:
    st.error(f"❌ Erreur d'initialisation : {e}")
    st.stop()

# 2. Test d'écriture
if st.button("Créer un profil test"):
    try:
        data = {
            "auth_username": "test_mycologue", 
            "inat_username": "myco_fan_123",
            "notion_user_name": "Jean Dupont"
        }
        # On insère la donnée
        response = supabase.table("user_profiles").insert(data).execute()
        st.success("✅ Écriture réussie dans Supabase !")
        st.write(response)
    except Exception as e:
        st.error(f"❌ Erreur lors de l'écriture : {e}")

# 3. Test de lecture
if st.button("Lire les profils"):
    response = supabase.table("user_profiles").select("*").execute()
    st.write(response.data)
