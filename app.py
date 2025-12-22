import streamlit as st
import pandas as pd
from pyinaturalist import get_observations, get_places_autocomplete
from notion_client import Client
from datetime import date

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Importateur Myco-Notion", page_icon="🍄", layout="wide")
st.title("🍄 Importateur iNaturalist → Notion")
st.caption("Configuration: Filtres naturels & Recherche de lieux")

# --- SECRETS MANAGEMENT ---
try:
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
    DATABASE_ID = st.secrets["DATABASE_ID"]
    has_secrets = True
except FileNotFoundError:
    has_secrets = False

# --- SIDEBAR (Connexion) ---
with st.sidebar:
    st.header("🔐 Connexion")
    if not has_secrets:
        st.warning("Mode manuel")
        NOTION_TOKEN = st.text_input("Token Notion", type="password")
        DATABASE_ID = st.text_input("ID Database")
    
    # We keep the User input in sidebar as a "global" setting or move it to main filters depending on preference.
    # Let's keep a default user setting here if needed, but allow override in filters.
    default_user = st.text_input("Utilisateur par défaut", value="mycosphaera")

# --- NOTION CLIENT ---
if NOTION_TOKEN:
    notion = Client(auth=NOTION_TOKEN)

# --- INTERFACE ---
tab1, tab2 = st.tabs(["🔎 Recherche & Filtres (iNat Style)", "🔢 Par Liste d'IDs"])
params = {}
run_import = False

with tab1:
    st.markdown("### Filtres d'observation")
    
    # Layout similar to iNaturalist: 3 Columns
    col_filters_1, col_filters_2, col_filters_3 = st.columns([1, 1, 1])

    with col_filters_1:
        st.markdown("**👤 Personne & Projet**")
        user_input = st.text_input("Utilisateur(s)", value=default_user, help="Séparez par des virgules")
        taxon_id = st.text_input("ID Taxon (ex: 47169 Fungi)", value="47169")

    with col_filters_2:
        st.markdown("**🌍 Lieu**")
        # --- PLACE SEARCH ENGINE ---
        place_query = st.text_input("Chercher un lieu (Ville, Province...)", placeholder="ex: Québec")
        selected_place_id = None
        
        if place_query:
            try:
                # Fetch suggestions from iNat API
                places = get_places_autocomplete(q=place_query, per_page=10)
                if places['results']:
                    # Create a dict { "Name (Type)": id }
                    place_options = {f"{p['display_name']} ({p['place_type_name']})": p['id'] for p in places['results']}
                    
                    selected_name = st.selectbox("� Sélectionner le lieu exact :", options=place_options.keys())
                    selected_place_id = place_options[selected_name]
                    st.success(f"Lieu sélectionné : ID {selected_place_id}")
                else:
                    st.warning("Aucun lieu trouvé.")
            except Exception as e:
                st.error(f"Erreur recherche lieu: {e}")
        else:
            st.info("Laissez vide pour le monde entier.")

    with col_filters_3:
        st.markdown("**📅 Date d'observation**")
        date_mode = st.radio("Type de date", ["Période", "Date exacte", "Tout"], index=0)
        
        d1, d2 = None, None
        if date_mode == "Date exacte":
            the_date = st.date_input("Date", value=date.today())
            d1, d2 = the_date, the_date
        elif date_mode == "Période":
            c_start, c_end = st.columns(2)
            d1 = c_start.date_input("Du", value=date(2024, 1, 1))
            d2 = c_end.date_input("Au", value=date.today())
        # "Tout" leaves d1, d2 as None

    st.divider()
    
    # Button centered or wide
    if st.button("Lancer la recherche 🚀", type="primary", use_container_width=True):
        # Prepare User List
        user_list = [u.strip() for u in user_input.split(',') if u.strip()]
        
        params = {
            "user_id": user_list,
            "d1": d1, 
            "d2": d2, 
            "taxon_id": taxon_id, 
            "place_id": selected_place_id, # The Magic ID found by search
            "per_page": 50, 
            "detail": "all"
        }
        run_import = True

with tab2:
    ids_input = st.text_area("IDs (séparés par virgules)")
    if st.button("Importer IDs Spécifiques", type="primary"):
        id_list = [x.strip() for x in ids_input.split(',') if x.strip().isdigit()]
        if id_list:
            params = {"id": id_list}
            run_import = True

# --- IMPORT LOGIC (UNCHANGED MAPPING) ---
if run_import and NOTION_TOKEN and DATABASE_ID:
    with st.status("Traitement en cours...", expanded=True) as status:
        try:
            obs_list = get_observations(**params)['results']
        except Exception as e:
            st.error(f"Erreur iNaturalist : {e}")
            st.stop()

        if not obs_list:
            st.warning("Aucune observation trouvée avec ces critères.")
            st.stop()

        st.write(f"🔎 {len(obs_list)} observations trouvées. Importation vers Notion...")
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

            # 2. BUILD CONTENT
            children = []
            if len(photos) > 1:
                children.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Galerie Photo"}}]}})
                for p in photos:
                    children.append({
                        "object": "block", 
                        "type": "image", 
                        "image": {"type": "external", "external": {"url": p['url'].replace("square", "large")}}
                    })

            # 3. MAPPING
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

            # 4. SEND
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

        status.update(label="✅ Terminé !", state="complete")
        st.success(f"Synchronisation réussie de {len(obs_list)} observations.")
