import streamlit as st
import pandas as pd
from pyinaturalist import get_observations
from notion_client import Client
from datetime import date

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Importateur Myco-Notion", page_icon="🍄")
st.title("🍄 Importateur iNaturalist → Notion")
st.caption("Configuration: Mapping OBNL (v2.0 - Multi-filtres)")

# --- SECRETS MANAGEMENT ---
try:
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
    DATABASE_ID = st.secrets["DATABASE_ID"]
    has_secrets = True
except FileNotFoundError:
    has_secrets = False

# --- SIDEBAR CONFIGURATION ---
with st.sidebar:
    st.header("Connexion")
    if not has_secrets:
        st.warning("Mode manuel (Secrets non détectés)")
        NOTION_TOKEN = st.text_input("Token Notion", type="password")
        DATABASE_ID = st.text_input("ID Database")
    
    st.divider()
    st.markdown("### 👥 Filtres Globaux")
    # NEW: Multiple users input
    inat_users_input = st.text_area(
        "Utilisateurs iNaturalist", 
        value="mycosphaera", 
        help="Séparez les noms par des virgules (ex: user1, user2)"
    )
    # NEW: Place ID input
    place_id_input = st.text_input(
        "ID du Lieu (Optionnel)",
        help="Entrez l'ID numérique du lieu (ex: 6712 pour Québec). Laissez vide pour tout."
    )

# --- NOTION CLIENT ---
if NOTION_TOKEN:
    notion = Client(auth=NOTION_TOKEN)

# --- INTERFACE ---
tab1, tab2 = st.tabs(["📅 Recherche Avancée", "🔢 Par Liste d'IDs"])
params = {}
run_import = False

with tab1:
    # NEW: Date Mode Selection
    date_mode = st.radio("Mode de sélection de date :", ["Plage de dates", "Date unique"], horizontal=True)
    
    c1, c2 = st.columns(2)
    d1, d2 = None, None
    
    if date_mode == "Date unique":
        the_date = c1.date_input("Sélectionner la date", value=date.today())
        d1, d2 = the_date, the_date
    else:
        d1 = c1.date_input("Date de début", value=date(2024, 1, 1))
        d2 = c2.date_input("Date de fin", value=date.today())
    
    taxon_id = st.text_input("ID Taxon (ex: 47169 pour Fungi)", value="47169")
    
    if st.button("Rechercher", type="primary"):
        # Process users list
        user_list = [u.strip() for u in inat_users_input.split(',') if u.strip()]
        
        params = {
            "user_id": user_list,
            "d1": d1, 
            "d2": d2, 
            "taxon_id": taxon_id, 
            "place_id": place_id_input if place_id_input else None,
            "per_page": 50, 
            "detail": "all"
        }
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
            # Note: pyinaturalist handles list of users automatically
            obs_list = get_observations(**params)['results']
        except Exception as e:
            st.error(f"Erreur iNaturalist : {e}")
            st.stop()

        if not obs_list:
            st.warning("Aucune observation trouvée avec ces critères.")
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
            
            # Place ID filter check (Visual confirmation)
            if place_id_input:
                 props["Place ID (Filtre)"] = {"rich_text": [{"text": {"content": place_id_input}}]} # Optional logging

            # 4. SEND TO NOTION
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
        st.success(f"Synchronisation réussie de {len(obs_list)} observations.")
