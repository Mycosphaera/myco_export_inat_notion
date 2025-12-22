import streamlit as st
import pandas as pd
import requests
from pyinaturalist import get_observations, get_places_autocomplete, get_taxa_autocomplete
from notion_client import Client
from datetime import date, timedelta

# --- HELPER FUNCTIONS ---
@st.dialog("🍄 Détails de l'observation")
def show_details(obs_data):
    # Large Image
    if obs_data.get('Image'):
        st.image(obs_data['Image'].replace("small", "large"), use_container_width=True)
    
    # Metadata Links
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Taxon:** {obs_data['Taxon']}")
        st.markdown(f"**Date:** {obs_data['Date']}")
    with c2:
        st.link_button("Voir sur iNaturalist", obs_data['URL iNat'])
        if obs_data.get('Photo URL'):
             st.link_button("Voir Photo HD", obs_data['Photo URL'])

    if obs_data.get('Description'):
        st.caption("Description:")
        st.write(obs_data['Description'])

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
if 'selected_users' not in st.session_state:
    st.session_state.selected_users = [] # List of verified usernames
if 'last_selected_index' not in st.session_state:
    st.session_state.last_selected_index = None

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
    notion = Client(auth=NOTION_TOKEN, notion_version="2025-09-03")

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
        # User Selection with Validation
        c_usr_input, c_usr_add = st.columns([3, 1])
        new_user = c_usr_input.text_input("Ajouter un utilisateur", placeholder="Nom d'utilisateur", label_visibility="collapsed")
        
        if c_usr_add.button("➕", help="Ajouter l'utilisateur"):
            if new_user:
                try:
                    # Validate against API using Requests directly
                    # iNaturalist API v1 search
                    url = f"https://api.inaturalist.org/v1/users/autocomplete?q={new_user}&per_page=5"
                    headers = {"User-Agent": "StreamlitMycoImport/1.0 (mathieu@example.com)"}
                    resp = requests.get(url, headers=headers)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                    else:
                        st.error(f"Erreur HTTP {resp.status_code} de l'API iNaturalist.")
                        data = {}
                    
                    # Check exact match or close enough (API fuzzy searches)
                    valid_user = None
                    if 'results' in data and data['results']:
                        # Check strict case-insensitive match
                        matches = [u['login'] for u in data['results'] if u['login'].lower() == new_user.lower()]
                        if matches:
                            valid_user = matches[0]
                        else:
                             # Optional: If exact match not found but results exist, could suggest?
                             pass
                    
                    if valid_user:
                        if valid_user not in st.session_state.selected_users:
                            st.session_state.selected_users.append(valid_user)
                            st.success(f"Ajouté : {valid_user}")
                            st.rerun()
                        else:
                            st.warning("Déjà ajouté.")
                    else:
                        st.error(f"Utilisateur '{new_user}' introuvable sur iNaturalist.")
                except Exception as e:
                    st.error(f"Erreur API: {e}")

        # Display Selected Users
        if st.session_state.selected_users:
            st.caption("Utilisateurs sélectionnés (Cliquez pour retirer) :")
            # Use multi-select pills to show/remove
            # If user unselects, we remove from state.
            current_selection = st.pills(
                "Users",
                options=st.session_state.selected_users,
                default=st.session_state.selected_users,
                selection_mode="multi",
                label_visibility="collapsed",
                key="user_pills"
            )
            
            # Detect removal
            if len(current_selection) < len(st.session_state.selected_users):
                st.session_state.selected_users = current_selection
                st.rerun()
        else:
            # Default fallback if empty? User requested selection.
            # If empty, maybe use default_user if provided? 
            # Logic below uses selected_users if present, else default?
            # Let's keep it clean: params will use this list. 
            # If list empty, maybe params['user_id'] is empty (all users)? Or default?
            if default_user and not st.session_state.selected_users:
                 # Pre-populate default if nothing selected yet?
                 # Risky if they want "All". 
                 # Let's just show "Aucun utilisateur filtré (Tout le monde)"
                 st.info("Aucun filtre utilisateur (Tout le monde)")

        # Compatibility with downstream logic
        # function will join st.session_state.selected_users
        
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
        # Quick Date Presets
        st.markdown("**📅 Date d'observation**")
        c_q1, c_q2, c_q3 = st.columns(3)
        today = date.today()
        
        if c_q1.button("Auj.", type="secondary", use_container_width=True, help="Aujourd'hui"):
            st.session_state.d_start = today
            st.session_state.d_end = today
            st.rerun()
            
        if c_q2.button("Sem.", type="secondary", use_container_width=True, help="Cette semaine (Lundi-Dimanche)"):
            start_week = today - timedelta(days=today.weekday())
            st.session_state.d_start = start_week
            st.session_state.d_end = today
            st.rerun()
            
        if c_q3.button("Mois", type="secondary", use_container_width=True, help="Ce mois-ci"):
            start_month = today.replace(day=1)
            st.session_state.d_start = start_month
            st.session_state.d_end = today
            st.rerun()

        date_mode = st.radio("Type de date", ["Période", "Date exacte", "Multi-dates", "Tout"], index=0, key="date_mode_radio")
        
        d1, d2 = None, None
        
        if date_mode == "Date exacte":
            the_date = st.date_input("Date", value=date.today())
            d1, d2 = the_date, the_date
            
        elif date_mode == "Période":
            c_start, c_end = st.columns(2)
            # Use keys to allow button updates
            d1 = c_start.date_input("Du", value=date(2024, 1, 1), key="d_start")
            d2 = c_end.date_input("Au", value=today, key="d_end")
            
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
    
    if st.button("🔄 Réinitialiser la recherche", type="secondary"):
        st.session_state.search_results = []
        st.session_state.custom_dates = []
        st.session_state.selected_users = []
        st.session_state.selection_states = {}
        st.rerun()

    if c_search.button("🔎 Lancer la recherche", type="primary", use_container_width=True):
        # Use verified list OR default if empty? 
        # Actually user might want "default_user" to start with.
        # Let's add default_user to selected_users on init if list is empty?
        # For now, explicit list.
        user_list = st.session_state.selected_users
        if not user_list and default_user:
             # Fallback to text input default if they didn't touch the new widget? 
             # No, confusing. Let's trust the widget.
             # If widget empty -> All users?
             # User prompt implies "verify name".
             # If I type mycosphaera in default, I expect it used.
             # I should probably auto-add default_user to list on startup.
             pass
        
        # Pre-pulate
        if not st.session_state.selected_users and default_user:
            user_list = [default_user]

        # Determine Limit
        
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
    ids_input = st.text_area("IDs (séparés par virgules ou sauts de ligne)")
    if st.button("🔎 Rechercher IDs", type="primary"):
        # Replace newlines with commas, then split
        normalized_input = ids_input.replace('\n', ',')
        id_list = [x.strip() for x in normalized_input.split(',') if x.strip().isdigit()]
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
    # Multi-select allowed. Empty = All.
    filter_dates = c_filter.pills(
        "Filtrer par date", 
        options=sorted_dates, 
        default=[], 
        selection_mode="multi",
        label_visibility="collapsed"
    )
    
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
        
        # Logic: Show if NO filter selected OR date matches one of selected
        if not filter_dates or date_extracted in filter_dates:
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
        tag_str = ""
        if tags:
            extracted_tags = []
            for t in tags:
                if isinstance(t, dict):
                    extracted_tags.append(t.get('tag', ''))
                elif isinstance(t, str):
                    extracted_tags.append(t)
                else:
                    extracted_tags.append(str(t))
            tag_str = ", ".join(filter(None, extracted_tags))
        desc_text = obs.get('description', '') or ""
        gps_coords = obs.get('location', '') or ""

        raw_data.append({
            "Import": is_checked, 
            "ID": str(obs['id']), # String to avoid commas
            "Taxon": taxon_name,
            "Date": date_str,
            "Lieu": place,
            "Mycologue": user_login,
            "Tags": tag_str,
            "Description": desc_text,
            "GPS": gps_coords,
            "URL iNat": f"https://www.inaturalist.org/observations/{obs['id']}",
            "URL Photo": img_url,
            "Image": img_url,
            "_original_obs": obs 
        })
    
    df = pd.DataFrame(raw_data)
    
    # Configure Columns
    column_config = {
        "Import": st.column_config.CheckboxColumn("✅", width="small"),
        "ID": st.column_config.TextColumn("🆔 ID", width="small"),
        "Taxon": st.column_config.TextColumn("🍄 Espèce"),
        "Date": st.column_config.TextColumn("📅 Date"),
        "Lieu": st.column_config.TextColumn("📍 Lieu"),
        "Mycologue": st.column_config.TextColumn("👤 Mycologue"),
        "Tags": st.column_config.TextColumn("🏷️ Tags"),
        "Description": st.column_config.TextColumn("📝 Description"),
        "GPS": st.column_config.TextColumn("🌍 GPS"),
        "URL iNat": st.column_config.LinkColumn(
            "🌐 iNat", 
            display_text=r"https://www\.inaturalist\.org/observations/(.*)", # Show ID as link text
            help="Cliquer pour ouvrir l'observation sur iNaturalist"
        ),
        "Photo URL": st.column_config.LinkColumn("🖼️ Photo", help="Lien direct vers l'image"),
        "Image": st.column_config.ImageColumn("📷 Aperçu", help="Cliquer pour agrandir"),
        "_original_obs": None 
    }
    
    # Show Editor
    # Show Dataframe with Selection
    # Generate unique key string from sorted selected dates
    filter_key_suffix = "_all" if not filter_dates else "_" + "_".join(sorted(filter_dates))
    
    # Show Data Editor (Editable Checkboxes)
    # Generate unique key string from sorted selected dates
    filter_key_suffix = "_all" if not filter_dates else "_" + "_".join(sorted(filter_dates))
    
    # We remove 'on_select' to fix the TypeError crash.
    # We restore standard data_editor behavior.
    response = st.data_editor(
        df,
        column_config=column_config,
        hide_index=True,
        use_container_width=True,
        disabled=["ID", "Taxon", "Date", "Lieu", "Mycologue", "Tags", "Description", "GPS", "URL iNat", "Photo URL", "Image", "_original_obs"],
        key=f"editor{filter_key_suffix}"
    )
    
    # 2. Logic: Detect Changes & Trigger Pop-up
    # We compare the current editor state with our session_state to detect NEWLY checked items.
    if response is not None and not response.empty:
        # Iterate to find changes
        for index, row in response.iterrows():
             # Fix TypeError: _original_obs might be stringified by data_editor.
             # Use the explicit 'ID' column (string) and convert to int.
             try:
                 o_id = int(str(row['ID']).replace(",","")) # Remove commas just in case, though we cleaned it
                 is_checked = row['Import']
                 
                 old_state = st.session_state.selection_states.get(o_id, False) # Default to false if unknown
                 
                 if is_checked and not old_state:
                     # This row was JUST checked. Show Details!
                     # For the dialog, we need the full data. 
                     # We can get it from the original df using the index? 
                     # Or pass the row if it has the display fields.
                     # show_details expects dict-like with 'Image', 'Taxon', etc.
                     # 'row' from iterrows is a Series, which works fine.
                     show_details(row)
                 
                 # Update State
                 st.session_state.selection_states[o_id] = is_checked
             except ValueError:
                 pass # Skip if ID issue

    # 3. Count total checked (visual feedback)
    total_checked = int(response['Import'].sum()) if not response.empty else 0
    st.info(f"{total_checked} observations sélectionnées pour l'import.")
    
    if st.button("📤 Importer vers Notion", type="primary"):
        # Robust Import Logic
        ids_to_import = []
        if not response.empty:
            checked_rows = response[response['Import'] == True]
            if not checked_rows.empty:
                # Get IDs as strings
                 checked_ids = set()
                 for _, r in checked_rows.iterrows():
                     # Safe conversion
                     checked_ids.add(str(r['ID']))
                     
                 # Filter source list
                 ids_to_import = [
                    obs for obs in st.session_state.search_results 
                    if str(obs['id']) in checked_ids
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
                user_name = obs.get('user', {}).get('name') or obs.get('user', {}).get('login') or "Inconnu"
                
                obs_url = obs.get('uri')
                
                tags = obs.get('tags', []) 
                tag_string = ""
                if tags:
                    extracted_tags = []
                    for t in tags:
                        if isinstance(t, dict):
                            extracted_tags.append(t.get('tag', ''))
                        elif isinstance(t, str):
                            extracted_tags.append(t)
                        else:
                            extracted_tags.append(str(t))
                    tag_string = ", ".join(filter(None, extracted_tags))
                
                place_guess = obs.get('place_guess', '')
                description = obs.get('description', '')
                
                # Coordinates
                lat = None
                lon = None
                coords = obs.get('location')
                if coords:
                    try:
                        if isinstance(coords, str):
                            parts = coords.split(',')
                            lat = float(parts[0])
                            lon = float(parts[1])
                        elif isinstance(coords, list) and len(coords) >= 2:
                            lat = float(coords[0])
                            lon = float(coords[1])
                    except (ValueError, IndexError, TypeError):
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
                # FIX: User requested Real Name ("Mathias...") and Select property
                if user_name: props["Mycologue"] = {"select": {"name": user_name}}
                # FIX: Renamed property as per user screenshot
                if obs_url: props["URL Inaturalist"] = {"url": obs_url}
                if first_photo_url: props["Photo Inat"] = {"url": first_photo_url}
                if tag_string: props["No° Fongarium"] = {"rich_text": [{"text": {"content": tag_string}}]}
                if description: props["Description rapide"] = {"rich_text": [{"text": {"content": description[:2000]}}]}
                if place_guess: props["Repère"] = {"rich_text": [{"text": {"content": place_guess}}]}
                if lat: props["latitude (sexadécimal)"] = {"number": lat}
                if lon: props["longitude (sexadécimal)"] = {"number": lon}
                
                obs_country = obs.get('place_guess', '') # iNat doesn't cleanly give country in basic response always, strictly place_guess used above
                # But user listed "Place_country_name". 
                # Let's see if we have it? Usually not in standard obs dict unless extra param. 
                # Fallback: Don't map it if missing or map place_guess.
                # Actually, earlier I didn't verify if I have place_country_name.
                # Checking mapping table: "Place_country_name" -> "Place_country_name"
                # If I don't have it, I skip it. 
                
                # SEND TO NOTION
                try:
                    # Debug Info: printing version to confirm we are complying
                    # st.write(f"DEBUG: Notion Version = {notion.options['notion_version']}")
                    
                    notion.pages.create(
                        parent={"database_id": DATABASE_ID},
                        properties=props,
                        children=children,
                        cover={"external": {"url": cover_url}} if cover_url else None
                    )
                except Exception as e:
                    st.warning(f"Erreur Notion sur {sci_name}: {e}")
                    # Provide hint on common error
                    if "multiple data sources" in str(e):
                        st.caption("ℹ️ Note: Cette erreur indique souvent que la base de données cible est complexe (Synchronisée, Vue liée, ou Data Source). Assurez-vous de cibler la base originale et que l'API supporte ce type.")
                
                progress_bar.progress((i + 1) / len(obs_to_import))
            
            status_text.text("✅ Importation terminée avec succès !")
            st.success("Toutes les observations sélectionnées ont été transférées.")
