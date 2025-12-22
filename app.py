import streamlit as st
import pandas as pd
from pyinaturalist import get_observations, get_places_autocomplete, get_taxa_autocomplete
from notion_client import Client
from datetime import date

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Importateur Myco-Notion", page_icon="🍄", layout="wide")
st.title("🍄 Importateur iNaturalist → Notion")
st.caption("Configuration: Filtres naturels & Recherche de lieux")

# --- STATE MANAGEMENT ---
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'show_selection' not in st.session_state:
    st.session_state.show_selection = False
if 'select_all' not in st.session_state:
    st.session_state.select_all = True # Default state

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
    
    default_user = st.text_input("Utilisateur par défaut", value="mycosphaera")

# --- NOTION CLIENT ---
if NOTION_TOKEN:
    notion = Client(auth=NOTION_TOKEN)

# --- INTERFACE ---
tab1, tab2 = st.tabs(["🔎 Recherche & Filtres (iNat Style)", "🔢 Par Liste d'IDs"])
params = {}
run_search = False
import_list = [] # Will hold IDs or Obs to import

with tab1:
    st.markdown("### Filtres d'observation")
    col_filters_1, col_filters_2, col_filters_3 = st.columns([1, 1, 1])

    with col_filters_1:
        st.markdown("**👤 Personne & Projet**")
        user_input = st.text_input("Utilisateur(s)", value=default_user, help="Séparez par des virgules")
        
        # --- TAXON SEARCH ENGINE ---
        taxon_query = st.text_input("Chercher un taxon (ex: Fungi)", placeholder="ex: Fungi")
        taxon_id = "47169" # Default to Fungi
        
        if taxon_query:
            try:
                taxa = get_taxa_autocomplete(q=taxon_query, per_page=10)
                if taxa['results']:
                    taxon_options = {f"{t['name']} ({t.get('preferred_common_name', 'No common name')}) - ID: {t['id']}": t['id'] for t in taxa['results']}
                    selected_taxon_name = st.selectbox("🍄 Sélectionner le taxon :", options=taxon_options.keys())
                    taxon_id = taxon_options[selected_taxon_name]
                    st.success(f"Taxon: {taxon_id}")
                else:
                    st.warning("Aucun taxon trouvé.")
            except Exception as e:
                st.error(f"Erreur recherche taxon: {e}")

    with col_filters_2:
        st.markdown("**🌍 Lieu**")
        place_query = st.text_input("Chercher un lieu (Ville, Province...)", placeholder="ex: Québec")
        selected_place_id = None
        
        if place_query:
            try:
                places = get_places_autocomplete(q=place_query, per_page=10)
                if places['results']:
                    place_options = {f"{p['display_name']} ({p.get('place_type_name', 'Type inconnu')})": p['id'] for p in places['results']}
                    selected_name = st.selectbox("📍 Sélectionner le lieu exact :", options=place_options.keys())
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

    st.divider()
    
    if st.button("🔎 Lancer la recherche", type="primary", use_container_width=True):
        user_list = [u.strip() for u in user_input.split(',') if u.strip()]
        params = {
            "user_id": user_list,
            "d1": d1, 
            "d2": d2, 
            "taxon_id": taxon_id, 
            "place_id": selected_place_id,
            "per_page": 50, # Modulable limit could be added
            "detail": "all"
        }
        run_search = True

with tab2:
    ids_input = st.text_area("IDs (séparés par virgules)")
    if st.button("🔎 Rechercher IDs", type="primary"):
        id_list = [x.strip() for x in ids_input.split(',') if x.strip().isdigit()]
        if id_list:
            params = {"id": id_list}
            run_search = True

# --- SEARCH EXECUTION ---
if run_search:
    with st.spinner("Recherche sur iNaturalist..."):
        try:
            results = get_observations(**params)['results']
            st.session_state.search_results = results
            st.session_state.show_selection = True
            if not results:
                st.warning("Aucune observation trouvée.")
        except Exception as e:
            st.error(f"Erreur iNaturalist : {e}")
            st.session_state.search_results = []

# --- SELECTION INTERFACE ---
if st.session_state.show_selection and st.session_state.search_results:
    st.divider()
    st.subheader(f"📋 Résultat : {len(st.session_state.search_results)} observations")
    
    # Bulk Selection Buttons
    c_sel1, c_sel2, c_space = st.columns([1, 1, 4])
    if c_sel1.button("✅ Tout sélectionner"):
        st.session_state.select_all = True
    if c_sel2.button("❌ Tout désélectionner"):
        st.session_state.select_all = False
        
    # Transform to DataFrame for Data Editor
    raw_data = []
    for obs in st.session_state.search_results:
        # Safe extraction for display
        taxon_name = obs.get('taxon', {}).get('name') if obs.get('taxon') else "Inconnu"
        
        # Robust Date extraction
        obs_date = obs.get('time_observed_at')
        if obs_date:
            date_str = obs_date.strftime("%Y-%m-%d")
        else:
            date_str = obs.get('observed_on_string', 'N/A')
            
        place = obs.get('place_guess', 'N/A')
        img_url = obs.get('photos')[0]['url'].replace("square", "small") if obs.get('photos') else None
        
        raw_data.append({
            "Import": st.session_state.select_all, # Use global state
            "ID": obs['id'],
            "Taxon": taxon_name,
            "Date": date_str,
            "Lieu": place,
            "Image": img_url,
            "_original_obs": obs # Hidden column to keep full object
        })
    
    df = pd.DataFrame(raw_data)
    
    # Configure Columns
    column_config = {
        "Import": st.column_config.CheckboxColumn("Sélectionner", default=True),
        "ID": st.column_config.NumberColumn("ID iNat"),
        "Taxon": st.column_config.TextColumn("Espèce"),
        "Date": st.column_config.TextColumn("Date"),
        "Lieu": st.column_config.TextColumn("Lieu"),
        "Image": st.column_config.ImageColumn("Aperçu"),
        "_original_obs": None # Hide this column
    }
    
    # Show Editor
    edited_df = st.data_editor(
        df,
        column_config=column_config,
        hide_index=True,
        use_container_width=True,
        disabled=["ID", "Taxon", "Date", "Lieu", "Image"] # Only allow checkbox editing
    )
    
    # Filter Selected
    selected_rows = edited_df[edited_df["Import"] == True]
    
    st.info(f"{len(selected_rows)} observations sélectionnées pour l'import.")
    
    if st.button("📤 Importer vers Notion", type="primary"):
        if selected_rows.empty:
            st.warning("Aucune observation sélectionnée.")
        elif NOTION_TOKEN and DATABASE_ID:
            # RETRIEVE FULL OBJECTS BASED ON SELECTION
            obs_to_import = selected_rows["_original_obs"].tolist()
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, obs in enumerate(obs_to_import):
                sci_name = obs.get('taxon', {}).get('name', 'Inconnu')
                status_text.text(f"Importation de {sci_name} ({i+1}/{len(obs_to_import)})...")
                
                # --- DATA EXTRACTION & MAPPING ---
                user_name = obs.get('user', {}).get('login', '')
                observed_on = obs.get('time_observed_at')
                date_iso = observed_on.isoformat() if observed_on else None
                obs_url = obs.get('uri')
                
                tags = obs.get('tags', []) 
                tag_string = ", ".join(t['tag'] for t in tags) if tags else ""
                
                place_guess = obs.get('place_guess', '')
                description = obs.get('description', '')
                
                # FIX: Robust Location Parsing
                coords = obs.get('location')
                lat, lon = None, None
                if coords and ',' in coords:
                    try:
                        parts = coords.split(',')
                        lat = float(parts[0])
                        lon = float(parts[1])
                    except (ValueError, IndexError):
                        pass # Keep None

                photos = obs.get('photos', [])
                cover_url = photos[0]['url'].replace("square", "medium") if photos else None
                first_photo_url = photos[0]['url'].replace("square", "original") if photos else None

                # BUILD CHILDREN (Gallery)
                children = []
                if len(photos) > 1:
                    children.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Galerie Photo"}}]}})
                    for p in photos:
                        children.append({
                            "object": "block", 
                            "type": "image", 
                            "image": {"type": "external", "external": {"url": p['url'].replace("square", "large")}}
                        })

                # MAPPING PROPS
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

                # SEND TO NOTION
                try:
                    notion.pages.create(
                        parent={"type": "database_id", "database_id": DATABASE_ID},
                        properties=props,
                        children=children,
                        cover={"external": {"url": cover_url}} if cover_url else None
                    )
                except Exception as e:
                    st.warning(f"Erreur Notion sur {sci_name}: {e}")
                
                progress_bar.progress((i + 1) / len(obs_to_import))
            
            status_text.text("✅ Importation terminée avec succès !")
            st.success("Toutes les observations sélectionnées ont été transférées.")
