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
if 'custom_dates' not in st.session_state:
    st.session_state.custom_dates = []
if 'selection_states' not in st.session_state:
    st.session_state.selection_states = {} # Map ID -> bool

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
        date_mode = st.radio("Type de date", ["Période", "Date exacte", "Multi-dates", "Tout"], index=0)
        
        d1, d2 = None, None
        
        if date_mode == "Date exacte":
            the_date = st.date_input("Date", value=date.today())
            d1, d2 = the_date, the_date
            
        elif date_mode == "Période":
            c_start, c_end = st.columns(2)
            d1 = c_start.date_input("Du", value=date(2024, 1, 1))
            d2 = c_end.date_input("Au", value=date.today())
            
        elif date_mode == "Multi-dates":
            c_add, c_btn = st.columns([2, 1])
            new_date = c_add.date_input("Ajouter une date", value=date.today(), label_visibility="collapsed")
            if c_btn.button("Ajouter", use_container_width=True):
                if new_date not in st.session_state.custom_dates:
                    st.session_state.custom_dates.append(new_date)
                    st.session_state.custom_dates.sort()
            
            if st.session_state.custom_dates:
                st.caption("Dates sélectionnées :")
                # Display simply
                for i, d in enumerate(st.session_state.custom_dates):
                    c_date, c_del = st.columns([4, 1])
                    c_date.code(d.strftime("%Y-%m-%d"))
                    if c_del.button("❌", key=f"del_{i}", help="Supprimer cette date"):
                        st.session_state.custom_dates.pop(i)
                        st.rerun()
                
                if st.button("🗑️ Effacer tout", type="secondary"):
                    st.session_state.custom_dates = []
                    st.rerun()
            else:
                st.info("Aucune date ajoutée.")

    st.divider()

    # Limit Selection
    c_search, c_limit = st.columns([3, 1])
    limit_option = c_limit.selectbox("Nombre de résultats", [50, 100, 200, 500, "Tout (Attention !)"], index=0)
    
    if c_search.button("🔎 Lancer la recherche", type="primary", use_container_width=True):
        user_list = [u.strip() for u in user_input.split(',') if u.strip()]
        
        # Determine Limit
        fetch_limit = 50
        if isinstance(limit_option, int):
            fetch_limit = limit_option
        else:
            fetch_limit = 10000 # "Tout" -> large number
            
        params = {
            "user_id": user_list,
            "d1": d1, 
            "d2": d2, 
            "taxon_id": taxon_id, 
            "place_id": selected_place_id,
            "per_page": 200, # Request max allowed per page
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
            results = []
            
            # Helper to fetch pages
            def fetch_with_pagination(api_params, max_count):
                collected = []
                page = 1
                while len(collected) < max_count:
                    # Adjust per_page if nearing limit
                    remaining = max_count - len(collected)
                    p_size = min(200, remaining) # Max 200 per call
                    
                    api_params['page'] = page
                    api_params['per_page'] = p_size
                    
                    batch = get_observations(**api_params)['results']
                    if not batch:
                        break
                        
                    collected.extend(batch)
                    if len(batch) < p_size: # End of results
                        break
                    
                    page += 1
                return collected

            # MULTI-DATE LOGIC
            if date_mode == "Multi-dates" and st.session_state.custom_dates:
                for d in st.session_state.custom_dates:
                    p = params.copy()
                    p['on'] = d # Specific API parameter for single date
                    # Remove d1/d2 if present to avoid conflict
                    p.pop('d1', None) 
                    p.pop('d2', None)
                    
                    # Fetch for this date (respecting global limit per date? or split limit? 
                    # Let's apply fetch_limit per date to avoid complexity, or just 200 per date)
                    # User likely expects "Tout" to include all dates fully.
                    # Simplification: Apply fetch_limit TO TOTAL is hard with loop.
                    # Let's fetch "Tout" for each date if requested.
                    
                    batch = fetch_with_pagination(p, fetch_limit)
                    results.extend(batch)
            else:
                # Standard Search
                results = fetch_with_pagination(params, fetch_limit)
            
            # Remove potential duplicates based on ID
            seen_ids = set()
            unique_results = []
            for r in results:
                if r['id'] not in seen_ids:
                    unique_results.append(r)
                    seen_ids.add(r['id'])
            
            # Automatic Sort
            unique_results.sort(
                key=lambda x: x.get('time_observed_at').isoformat() if x.get('time_observed_at') else "0000-00-00", 
                reverse=True
            )
            
            st.session_state.search_results = unique_results
            # Init selection state: Default All True
            st.session_state.selection_states = {r['id']: True for r in unique_results}
            
            st.session_state.show_selection = True
            if not unique_results:
                st.warning("Aucune observation trouvée.")
        except Exception as e:
            st.error(f"Erreur iNaturalist : {e}")
            st.session_state.search_results = []

# --- SELECTION INTERFACE ---
if st.session_state.show_selection and st.session_state.search_results:
    st.divider()
    
    # --- RESULT FILTERING ---
    # Extract unique dates
    all_dates = set()
    for obs in st.session_state.search_results:
        # Priority 1: time_observed_at (datetime obj or string)
        d_val = obs.get('time_observed_at')
        date_extracted = None
        
        if d_val:
            if hasattr(d_val, 'strftime'):
                date_extracted = d_val.strftime("%Y-%m-%d")
            else:
                # Force string conversion and slice first 10 chars "YYYY-MM-DD"
                date_extracted = str(d_val)[:10]
        
        # Priority 2: observed_on (usually string "YYYY-MM-DD")
        if not date_extracted:
            d_on = obs.get('observed_on')
            if d_on:
               date_extracted = str(d_on)[:10]

        # Priority 3: observed_on_string (fallback)
        if not date_extracted:
             d_str_fallback = obs.get('observed_on_string')
             if d_str_fallback:
                 date_extracted = str(d_str_fallback)[:10]
        
        if date_extracted:
            all_dates.add(date_extracted)
        else:
            all_dates.add("date_inconnue")
    
    sorted_dates = sorted(list(all_dates), reverse=True)
    
    c_title, c_filter = st.columns([1, 2])
    c_title.subheader(f"📋 Résultat : {len(st.session_state.search_results)} obs")
    
    # Use st.pills for "Etiquettes" (requires Streamlit 1.40+)
    filter_date = c_filter.pills(
        "Filtrer par date", 
        options=["Tout"] + sorted_dates, 
        default="Tout", 
        selection_mode="single",
        label_visibility="collapsed"
    )
    
    if not filter_date: 
        filter_date = "Tout" # Fallback if deselected
    
    # Filter Data
    visible_obs = []
    for obs in st.session_state.search_results:
        # Same extraction logic for matching
        d_val = obs.get('time_observed_at')
        date_extracted = None
        
        if d_val:
            if hasattr(d_val, 'strftime'):
                date_extracted = d_val.strftime("%Y-%m-%d")
            else:
                date_extracted = str(d_val)[:10]
        
        if not date_extracted:
            d_on = obs.get('observed_on')
            if d_on:
               date_extracted = str(d_on)[:10]

        if not date_extracted:
             d_str_fallback = obs.get('observed_on_string')
             if d_str_fallback:
                 date_extracted = str(d_str_fallback)[:10]
                 
        if not date_extracted:
            date_extracted = "date_inconnue"
        
        if filter_date == "Tout" or date_extracted == filter_date:
            visible_obs.append(obs)

    # Bulk Selection Buttons (Apply to VISIBLE only)
    c_sel1, c_sel2, c_space = st.columns([1, 1, 4])
    if c_sel1.button("✅ Tout sélectionner (Vue)"):
        for o in visible_obs:
            st.session_state.selection_states[o['id']] = True
        st.rerun()
            
    if c_sel2.button("❌ Tout désélectionner (Vue)"):
        for o in visible_obs:
            st.session_state.selection_states[o['id']] = False
        st.rerun()
        
    # Transform to DataFrame for Data Editor
    raw_data = []
    for obs in visible_obs:
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
        
        # Determine Checkbox State from Persistent Map
        is_checked = st.session_state.selection_states.get(obs['id'], True)
        
        # Extended Metadata
        user_login = obs.get('user', {}).get('login', 'N/A')
        tags = obs.get('tags', [])
        tag_str = ", ".join([t['tag'] for t in tags]) if tags else ""
        desc_text = obs.get('description', '') or ""
        gps_coords = obs.get('location', '') or ""

        raw_data.append({
            "Import": is_checked, 
            "ID": obs['id'],
            "Taxon": taxon_name,
            "Date": date_str,
            "Lieu": place,
            "Mycologue": user_login,
            "Tags": tag_str,
            "Description": desc_text,
            "GPS": gps_coords,
            "Image": img_url,
            "_original_obs": obs 
        })
    
    df = pd.DataFrame(raw_data)
    
    # Configure Columns
    column_config = {
        "Import": st.column_config.CheckboxColumn("Sélectionner"),
        "ID": st.column_config.NumberColumn("ID iNat"),
        "Taxon": st.column_config.TextColumn("Espèce"),
        "Date": st.column_config.TextColumn("Date"),
        "Lieu": st.column_config.TextColumn("Lieu"),
        "Mycologue": st.column_config.TextColumn("Mycologue"),
        "Tags": st.column_config.TextColumn("No° Fongarium (Tags)"),
        "Description": st.column_config.TextColumn("Description"),
        "GPS": st.column_config.TextColumn("GPS"),
        "Image": st.column_config.ImageColumn("Aperçu"),
        "_original_obs": None 
    }
    
    # Show Editor
    edited_df = st.data_editor(
        df,
        column_config=column_config,
        hide_index=True,
        use_container_width=True,
        disabled=["ID", "Taxon", "Date", "Lieu", "Mycologue", "Tags", "Description", "GPS", "Image"],
        key=f"editor_{filter_date}" # Unique key to reset state on filter change
    )
    
    # SYNC BACK TO STATE
    # Iterate over edited rows to update master state
    for index, row in edited_df.iterrows():
        st.session_state.selection_states[row['ID']] = row['Import']
    
    # Count total selected
    total_selected = sum(st.session_state.selection_states.values())
    
    st.info(f"{total_selected} observations sélectionnées pour l'import (Total).")
    
    if st.button("📤 Importer vers Notion", type="primary"):
        # Gather all IDs that are True in selection_states AND exist in search_results
        ids_to_import = [
            obs for obs in st.session_state.search_results 
            if st.session_state.selection_states.get(obs['id'], False)
        ]
        
        if not ids_to_import:
            st.warning("Aucune observation sélectionnée.")
        elif NOTION_TOKEN and DATABASE_ID:
            # OBS TO IMPORT
            obs_to_import = ids_to_import # Already list of dicts
            
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
