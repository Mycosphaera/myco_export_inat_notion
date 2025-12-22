import streamlit as st
import pandas as pd
from pyinaturalist import get_observations
from notion_client import Client
from datetime import date

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Importateur Myco-Notion", page_icon="🍄")
st.title("🍄 Importateur iNaturalist → Notion")
st.caption("Configuration: Mapping OBNL (Version 2025)")

# --- SECRETS MANAGEMENT ---
try:
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
    DATABASE_ID = st.secrets["DATABASE_ID"]
    has_secrets = True
except FileNotFoundError:
    has_secrets = False

with st.sidebar:
    st.header("Connexion")
    if not has_secrets:
        st.warning("Mode manuel (Secrets non détectés)")
        NOTION_TOKEN = st.text_input("Token Notion", type="password")
        DATABASE_ID = st.text_input("ID Database")
    inat_user = st.text_input("Utilisateur iNaturalist", value="votre_nom_utilisateur")

# --- NOTION CLIENT ---
if NOTION_TOKEN:
    # Allow client to negotiate the best version, ensuring compatibility
    notion = Client(auth=NOTION_TOKEN)

# --- INTERFACE ---
tab1, tab2 = st.tabs(["📅 Par Filtres", "🔢 Par Liste d'IDs"])
params = {}
run_import = False

with tab1:
    c1, c2 = st.columns(2)
    date_start = c1.date_input("Début", value=date(2024, 1, 1))
    date_end = c2.date_input("Fin", value="today")
    taxon_id = st.text_input("ID Taxon (ex: 47169)", value="47169")
    if st.button("Rechercher", type="primary"):
        params = {"user_id": inat_user, "d1": date_start, "d2": date_end, "taxon_id": taxon_id, "per_page": 50, "detail": "all"}
        run_import = True

with tab2:
    ids_input = st.text_area("IDs (séparés par virgules)")
    if st.button("Importer IDs", type="primary"):
        id_list = [x.strip() for x in ids_input.split(',') if x.strip().isdigit()]
        if id_list:
            params = {"id": id_list}
            run_import = True

# --- IMPORT LOGIC ---
if run_import and NOTION_TOKEN and DATABASE_ID:
    with st.status("Traitement en cours...", expanded=True) as status:
        try:
            obs_list = get_observations(**params)['results']
        except Exception as e:
            st.error(f"Erreur iNaturalist : {e}")
            st.stop()

        st.write(f"Traitement de {len(obs_list)} observations...")
        bar = st.progress(0)
        
        for i, obs in enumerate(obs_list):
            # 1. EXTRACT DATA
            taxon = obs.get('taxon')
            sci_name = taxon.get('name') if taxon else (obs.get('species_guess') or "Inconnu")
            user_name = obs.get('user', {}).get('login', '')
            
            observed_on = obs.get('time_observed_at')
            date_iso = observed_on.isoformat() if observed_on else None
            
            obs_url = obs.get('uri')
            
            tags = obs.get('tags', []) 
            tag_string = ", ".join(t['tag'] for t in tags) if tags else ""
            
            place_guess = obs.get('place_guess', '')
            description = obs.get('description', '')
            
            coords = obs.get('location')
            lat, lon = map(float, coords.split(',')) if coords else (None, None)

            photos = obs.get('photos', [])
            cover_url = photos[0]['url'].replace("square", "medium") if photos else None
            first_photo_url = photos[0]['url'].replace("square", "original") if photos else None

            # 2. BUILD CONTENT (Gallery)
            children = []
            if len(photos) > 1:
                children.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Galerie Photo"}}]}})
                for p in photos:
                    children.append({
                        "object": "block", 
                        "type": "image", 
                        "image": {"type": "external", "external": {"url": p['url'].replace("square", "large")}}
                    })

            # 3. MAPPING (Specific to User DB)
            props = {}
            props["Titre"] = {"title": [{"text": {"content": sci_name}}]}
            
            if date_iso: props["Date"] = {"date": {"start": date_iso}}
            if user_name: props["Mycologue"] = {"rich_text": [{"text": {"content": user_name}}]}
            if obs_url: props["URL iNat"] = {"url": obs_url}
            if first_photo_url: props["Photo Inat"] = {"url": first_photo_url}
            if tag_string: props["No° Fongarium"] = {"rich_text": [{"text": {"content": tag_string}}]}
            if description: props["Description rapide"] = {"rich_text": [{"text": {"content": description[:2000]}}]}
            if place_guess: props["Repère"] = {"rich_text": [{"text": {"content": place_guess}}]}
            if lat: props["latitude (sexadécimal)"] = {"number": lat}
            if lon: props["longitude (sexadécimal)"] = {"number": lon}

            # 4. SEND TO NOTION
            # Explicit parent type for API 2025 compatibility
            parent_obj = {"type": "database_id", "database_id": DATABASE_ID}

            try:
                notion.pages.create(
                    parent=parent_obj,
                    properties=props,
                    children=children,
                    cover={"external": {"url": cover_url}} if cover_url else None
                )
            except Exception as e:
                st.warning(f"Erreur sur {sci_name}: {e}")

            bar.progress((i + 1) / len(obs_list))

        status.update(label="Importation terminée !", state="complete")
        st.success("Synchronisation réussie.")
