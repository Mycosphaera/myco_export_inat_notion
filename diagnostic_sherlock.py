import streamlit as st
import socket
import requests

st.title("🕵️‍♂️ Diagnostic Sherlock Holmes")

# --- TEST 1 : LE PIÈGE INVISIBLE ---
st.subheader("1. Inspection de l'URL")
try:
    if "supabase" in st.secrets and "url" in st.secrets["supabase"]:
        url_secrete = st.secrets["supabase"]["url"]
        # J'ajoute des barres | autour pour voir s'il y a des espaces
        st.code(f"|{url_secrete}|", language="text") 
        
        if " " in url_secrete:
            st.error("🚨 ALERTE : Il y a un espace vide dans ton URL ! (Regarde bien entre les barres)")
        elif not url_secrete.startswith("https://"):
            st.error("🚨 ALERTE : L'URL ne commence pas par https://")
        else:
            st.success("✅ L'URL semble propre (pas d'espaces, format correct).")
            
        # --- TEST 3 : RÉSOLUTION DNS SUPABASE ---
        # Déplacé ici car il dépend de url_secrete
        st.subheader("3. Test DNS Supabase")
        try:
            # On nettoie l'URL pour garder juste le domaine (ex: blabla.supabase.co)
            hostname = url_secrete.replace("https://", "").replace("/", "").strip()
            st.write(f"Tentative de contact avec : `{hostname}`")
            
            ip = socket.gethostbyname(hostname)
            st.success(f"✅ SUCCÈS ! Supabase trouvé à l'adresse IP : {ip}")
        except Exception as e:
            st.error(f"❌ ÉCHEC : Impossible de trouver l'adresse de Supabase. ({e})")
            
    else:
        st.error("❌ Clé [supabase] -> url manquante dans secrets.toml")

except Exception as e:
    st.error(f"Impossible de lire secrets.toml : {e}")

# --- TEST 2 : ACCÈS INTERNET GÉNÉRAL ---
st.subheader("2. Test Internet (Google)")
try:
    requests.get("https://www.google.com", timeout=3)
    st.success("✅ Ton application a bien accès à internet.")
except Exception as e:
    st.error(f"❌ Ton environnement Antigravity semble bloqué : impossible de sortir sur internet. ({e})")
