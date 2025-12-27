import streamlit as st
import pandas as pd
import requests
from pyinaturalist import get_observations, get_places_autocomplete, get_taxa_autocomplete
from notion_client import Client
from datetime import date, timedelta
from labels import generate_label_pdf
from database import get_user_by_email, create_user_profile, log_action, update_user_profile
from whitelist import AUTHORIZED_USERS
import re


# --- SECRETS MANAGEMENT ---
try:
    NOTION_TOKEN = st.secrets["notion"]["token"] if "notion" in st.secrets else st.secrets["NOTION_TOKEN"]
    DATABASE_ID = st.secrets["notion"]["database_id"] if "notion" in st.secrets else st.secrets["DATABASE_ID"]
    has_secrets = True
except Exception:
    try:
         # Fallback old flat structure
         NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
         DATABASE_ID = st.secrets["DATABASE_ID"]
         has_secrets = True
    except:
         has_secrets = False
         NOTION_TOKEN = None
         DATABASE_ID = None

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Portail Myco", layout="wide")

# --- 2. GESTION DE LA SESSION ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'username' not in st.session_state:
    st.session_state.username = ""
if 'user_info' not in st.session_state:
    st.session_state.user_info = {} # To store full profile

def get_notion_mycologists():
    """Récupère la liste des options de la propriété 'Mycologue' dans Notion"""
    try:
        if not has_secrets: return []
        # On utilise le client global 'notion' initialisé plus bas, ou on le recrée localement
        # Pour être sûr, on le recrée ici car 'notion' est init plus bas dans le script
        local_notion = Client(auth=NOTION_TOKEN, notion_version="2022-06-28") 
        
        db = local_notion.databases.retrieve(DATABASE_ID)
        props = db.get("properties", {})
        
        # On cherche la colonne "Mycologue" (Select ou Multi-select)
        myco_prop = props.get("Mycologue", {})
        options = []
        
        if myco_prop.get("type") == "select":
            options = [opt["name"] for opt in myco_prop.get("select", {}).get("options", [])]
        elif myco_prop.get("type") == "multi_select":
            options = [opt["name"] for opt in myco_prop.get("multi_select", {}).get("options", [])]
            
        return sorted(options)
    except Exception as e:
        print(f"Erreur Retrieve Notion Schema: {e}")
        return []

# --- 3. FONCTION DE LOGIN / PORTAIL ---
def login_page():
    st.markdown("""
    <h1 style='text-align: center; color: #2E8B57;'>🍄 Portail Myco</h1>
    <p style='text-align: center;'>Identifiez-vous pour accéder à vos outils.</p>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab_login, tab_register = st.tabs(["🔑 Connexion", "✨ Créer mon portail"])
        
        # --- TAB CONNEXION (Step 0) ---
        with tab_login:
            with st.form("login_form"):
                email_input = st.text_input("Adresse Email").lower().strip()
                submit_login = st.form_submit_button("Accéder à mon espace")
                
                if submit_login:
                    user = get_user_by_email(email_input)
                    if user:
                        st.session_state.authenticated = True
                        st.session_state.user_info = user
                        st.session_state.username = user.get("notion_user_name", email_input)
                        st.session_state.inat_username = user.get("inat_username", "")
                        
                        # Auto-fill filters right here on login!
                        if st.session_state.inat_username:
                            st.session_state.selected_users = [st.session_state.inat_username]
                        
                        st.success(f"Bienvenue, {st.session_state.username} !")
                        st.rerun()
                    else:
                        st.error("Email inconnu. Avez-vous créé votre portail ?")

        # --- TAB INSCRIPTION (Wizard) ---
        with tab_register:
            
            # Étape 1 : Vérification Email (Whitelist)
            if 'reg_step' not in st.session_state:
                st.session_state.reg_step = 1
            if 'reg_email' not in st.session_state:
                st.session_state.reg_email = ""

            if st.session_state.reg_step == 1:
                st.write("#### Étape 1 : Vérification")
                st.info("L'accès est restreint aux membres autorisés.")
                
                email_check = st.text_input("Votre Email", key="reg_email_input").lower().strip()
                
                if st.button("Vérifier mon éligibilité"):
                    if not email_check:
                        st.warning("Entrez un email.")
                    else:
                        # RÈGLE : Liste expresse OU domaine @mycosphaera.com
                        is_authorized = False
                        if email_check.endswith("@mycosphaera.com"):
                           is_authorized = True
                        elif email_check in [u.lower() for u in AUTHORIZED_USERS]:
                           is_authorized = True
                           
                        if is_authorized:
                            st.session_state.reg_email = email_check
                            st.session_state.reg_step = 2
                            st.rerun()
                        else:
                            st.error("⛔ Désolé, cet email n'est pas autorisé.")

            
            # Étape 2 : Création Profil
            elif st.session_state.reg_step == 2:
                st.write("#### Étape 2 : Création du Profil")
                st.success(f"✅ Email autorisé : {st.session_state.reg_email}")
                
                # Fetch Notion Mycologists List (Try, default to empty)
                myco_options = get_notion_mycologists()
                
                with st.form("create_profile_form"):
                    # Email est pré-rempli et verrouillé (puisque validé)
                    st.text_input("Votre Email", value=st.session_state.reg_email, disabled=True)
                    
                    # Fallback Logic: Si la liste est vide (erreur ou pas de droits), on met un champ texte libre
                    if myco_options:
                        reg_notion_name = st.selectbox("Votre Nom sur Notion (Mycologue)", options=myco_options)
                    else:
                        st.warning("⚠️ Impossible de charger la liste Notion (droits insuffisants ?). Entrez votre nom manuellement.")
                        reg_notion_name = st.text_input("Votre Nom sur Notion (Mycologue)")
                    
                    reg_inat = st.text_input("Votre Nom d'utilisateur iNaturalist")
                    
                    if st.form_submit_button("Finaliser mon portail"):
                        if not reg_inat or not reg_notion_name:
                            st.warning("Tout remplir SVP.")
                        else:
                            # On utilise reg_email du state
                            success = create_user_profile(st.session_state.reg_email, reg_notion_name, reg_inat)
                            if success:
                                st.balloons()
                                st.success("Portail créé ! Vous pouvez maintenant vous connecter.")
                                st.session_state.reg_step = 1 # Reset
                            else:
                                st.error("Erreur technique.")
                
                if st.button("Retour"):
                    st.session_state.reg_step = 1
                    st.rerun()

# --- 4. LE GARDIEN (GATEKEEPER) ---
if not st.session_state.authenticated:
    login_page()
    st.stop() # ⛔ ARRÊT IMMÉDIAT du script ici si pas connecté

# =========================================================
# 🏰 BIENVENUE DANS LA CITADELLE (Ton App commence ici)
# =========================================================

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

@st.cache_data(ttl=300, show_spinner=False)
def count_user_notion_obs(token, db_id, target_user):
    """
    Compte précis des observations Notion filtrées par utilisateur.
    Met en cache le résultat pour 5 minutes.
    """
    if not token or not db_id or not target_user: return 0
    
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    # Payload: Filter by Mycologue
    # Optimisation: On ne récupère que l'ID pour aller plus vite (filter_properties)
    # Note: filter_properties réduit la payload reponse, mais on doit quand même paginer.
    payload = {
        "filter": {
            "property": "Mycologue",
            "select": {
                "equals": target_user
            }
        },
        "page_size": 100
    }
    
    total_count = 0
    has_more = True
    next_cursor = None
    
    try:
        while has_more:
            if next_cursor:
                payload["start_cursor"] = next_cursor
            
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                print(f"Error Counting: {resp.status_code} {resp.text}")
                break
                
            data = resp.json()
            results = data.get("results", [])
            total_count += len(results)
            
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
            
    except Exception as e:
        print(f"Count Error: {e}")
        return 0
        
    return total_count

@st.cache_data(ttl=600, show_spinner=False)
def get_last_fongarium_number_v2(token, db_id, target_user, prefix):
    """
    Récupère le dernier numéro de fongarium attribué pour un utilisateur donné.
    Ignore les codes temporaires (XXXX).
    Retourne (dernier_code, code_suivant_suggéré).
    """
    if not token or not db_id or not target_user or not prefix: return None, None

    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    # Payload
    payload = {
        "filter": {
            "and": [
                {
                    "property": "Mycologue",
                    "select": {
                        "equals": target_user
                    }
                },
                {
                    "property": "No° fongarium", # Nom colonne Notion
                    "rich_text": {
                        "starts_with": prefix
                    }
                }
            ]
        },
        "sorts": [
            {
                "property": "No° fongarium",
                "direction": "descending" # On veut le plus grand
            }
        ],
        "page_size": 30 # On en prend 30 pour être sûr de sauter les XXXX
    }

    # Regex strict : Prefix + Digits only (e.g. MRD0015)
    # Case insensitive match for prefix, but digits at end
    regex_pattern = re.compile(f"^{re.escape(prefix)}\d+$", re.IGNORECASE)

    try:
        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            print(f"Sort Error: {resp.text}")
            return None, None
            
        data = resp.json()
        results = data.get("results", [])
        
        for r in results:
            props = r["properties"]
            fong_val = constants_extract_text(props.get("No° fongarium", {}))
            if not fong_val:
                 fong_val = constants_extract_text(props.get("No fongarium", {}))
            
            if fong_val and regex_pattern.match(fong_val.strip()):
                # Found a match!
                last_val = fong_val.strip()
                
                # Calculate Next
                try:
                    # Extract number part
                    # Remove prefix (case insensitive replace)
                    num_part_str = last_val[len(prefix):]
                    num_val = int(num_part_str)
                    next_num = num_val + 1
                    # Format with same padding? len(num_part_str)
                    next_val_str = f"{next_num:0{len(num_part_str)}d}"
                    next_code = f"{prefix}{next_val_str}"
                    return last_val, next_code
                except:
                    return last_val, None
            
    except Exception as e:
        print(f"Fongarium Fetch Error: {e}")
        return None, None
        
    return None, None

@st.cache_data(ttl=300, show_spinner="Chargement Notion...")
def fetch_notion_data(token, db_id, notion_filter_and, max_fetch=50):
    """
    Cached function to fetch Notion data.
    notion_filter_and: The list of AND clauses for the filter.
    Returns: list of results
    """
    if not token or not db_id: return []
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    api_url_query = f"https://api.notion.com/v1/databases/{db_id}/query"
    
    all_results = []
    has_more = True
    next_cursor = None
    
    # Safety Cap for recursion to avoid timeouts in cache
    # But max_fetch controls this.
    
    while has_more and len(all_results) < max_fetch:
        # Payload
        query_payload = {
            "page_size": min(100, max_fetch - len(all_results)), # Max 100 per API call
            "sorts": [{"timestamp": "created_time", "direction": "descending"}]
        }
        
        if notion_filter_and:
             query_payload["filter"] = {"and": notion_filter_and}
             
        if next_cursor:
            query_payload["start_cursor"] = next_cursor
        
        resp_query = requests.post(api_url_query, headers=headers, json=query_payload)
        
        if resp_query.status_code != 200:
             # st.error? We are in a cached function. Returning error might be bad.
             # Return what we have.
             print(f"Fetch Error: {resp_query.text}")
             break
        else:
            data = resp_query.json()
            batch = data.get("results", [])
            all_results.extend(batch)
            
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
            
            if max_fetch <= 100 and len(all_results) >= max_fetch: break
            
    return all_results

def constants_extract_text(prop_obj):
    # Helper to extract text from Rich Text property safely
    if not prop_obj: return ""
    rtype = prop_obj.get("type")
    if rtype == "rich_text":
        content = prop_obj.get("rich_text", [])
        if content:
            return content[0].get("text", {}).get("content", "")
    elif rtype == "title":
         content = prop_obj.get("title", [])
         if content:
            return content[0].get("text", {}).get("content", "")
    return ""


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
    # Auto-fill from user_info if verified
    default_u = st.session_state.get("inat_username", "")
    st.session_state.selected_users = [default_u] if default_u else []
    st.session_state.last_selected_index = None
if 'editor_key_version' not in st.session_state:
    st.session_state.editor_key_version = 0

# --- SECRETS MANAGEMENT ---
# (Moved to top of script)
has_secrets = True if NOTION_TOKEN else False

# --- SUPABASE CLIENT ---
# Géré via database.py maintenant
supabase_client = None # Placeholder si le reste du code l'utilise encore, mais on devrait utiliser database.supabase
from database import supabase as supabase_client # Alias pour compatibilité rétroactive locale

# --- NOTION CLIENT ---
if NOTION_TOKEN:
    notion = Client(auth=NOTION_TOKEN, notion_version="2022-06-28")

# --- NAVIGATION SIDEBAR ---
with st.sidebar:
    st.header(f"👤 {st.session_state.username}")
    
    # Profile Photo (if available in schema)
    user_info = st.session_state.get('user_info', {})
    photo_url = user_info.get('photo_url')
    if photo_url: # Only if user added the column manually
        st.image(photo_url, width=100)
    
    nav_mode = st.radio("Navigation", ["📊 Tableau de Bord", "👤 Mon Profil"], label_visibility="collapsed")
    
    st.divider()
    if st.button("Se déconnecter"):
        st.session_state.authenticated = False
        st.rerun()

    st.caption("v1.2 (Regex Match)")

# --- MAIN CONTENT SWITCHER ---

if nav_mode == "👤 Mon Profil":
    st.title("👤 Mon Profil")
    st.info("Gérez vos informations personnelles et vos liens.")
    
    # Fetch latest data from verified DB record
    u_data = st.session_state.user_info
    
    with st.form("profile_update_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            new_notion = st.text_input("Nom Notion", value=u_data.get("notion_user_name", ""), help="Utilisé pour pré-remplir les filtres Notion.")
            new_inat = st.text_input("Utilisateur iNaturalist", value=u_data.get("inat_username", ""), help="Utilisé pour pré-remplir les recherches iNat.")
        
        with col_p2:
            # New Fields (Optional, might error if cols missing)
            new_prefix = st.text_input("Préfixe Fongarium", value=u_data.get("fongarium_prefix", ""), placeholder="ex: MRD", help="Identifiant de 3-4 lettres")
            new_photo = st.text_input("URL Photo de Profil", value=u_data.get("photo_url", ""), placeholder="https://...")
            new_bio = st.text_area("Bio / Description", value=u_data.get("bio", ""), placeholder="Mycologue passionné...")
            new_fb = st.text_input("Lien Facebook", value=u_data.get("social_fb", ""), placeholder="https://facebook.com/...")
            new_insta = st.text_input("Lien Instagram", value=u_data.get("social_insta", ""), placeholder="https://instagram.com/...")

        save_profile = st.form_submit_button("Enregistrer les modifications")
        
        if save_profile:
            # Prepare updates
            updates = {
                "notion_user_name": new_notion,
                "inat_username": new_inat
            }
            # Try to add optional fields to update dict
            if new_prefix: updates["fongarium_prefix"] = new_prefix
            if new_photo: updates["photo_url"] = new_photo
            if new_bio:   updates["bio"] = new_bio
            if new_fb:    updates["social_fb"] = new_fb
            if new_insta: updates["social_insta"] = new_insta
            
            res = update_user_profile(u_data["id"], updates)
            if res is True:
                st.success("Profil mis à jour ! Re-connectez vous pour voir tous les changements.")
                # Update local session mostly for display
                st.session_state.user_info.update(updates)
                st.session_state.username = new_notion
                st.session_state.inat_username = new_inat
                st.rerun()
            else:
                st.error(f"Erreur : {res}")
                if "column" in str(res).lower() and "does not exist" in str(res).lower():
                    st.warning("⚠️ Il semble que votre base Supabase n'ait pas les colonnes pour la photo ou la bio.")
                    st.code("""ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS photo_url text;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS bio text;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS social_fb text;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS social_insta text;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS fongarium_prefix text;
""", language="sql")

elif nav_mode == "📊 Tableau de Bord":
    # --- HEADER / DASHBOARD ---
    st.markdown("""
    <div class="brand-container">
        <p class="brand-tag">MYCOSPHAERA</p>
        <h1 class="main-title">iNat Sync</h1>
        <p class="subtitle">Gestionnaire d'observations & passerelle Notion</p>
    </div>
    """, unsafe_allow_html=True)

    # --- DASHBOARD STATS ---
    if st.session_state.authenticated:
        st_col1, st_col2, st_col3 = st.columns(3)
        
        # Stat 1: iNat Total
        with st_col1:
            try:
                # Quick fetch single ID
                # We prioritize logged in user
                target_user = st.session_state.inat_username or "mycosphaera"
                # API Call with per_page=0 just to get total_results
                stat_api = get_observations(user_id=target_user, per_page=0)
                total_inat = stat_api.get("total_results", 0)
                st.metric(label=f"Obs. iNaturalist ({target_user})", value=total_inat)
            except:
                st.metric(label="Obs. iNaturalist", value="--")

        # Stat 2: Notion (Count)
        with st_col2:
            if has_secrets:
                # Use cached function
                # We use the specific notion name stored in session
                myco_name = st.session_state.username
                if myco_name:
                    with st.spinner("Calcul..."):
                        n_count = count_user_notion_obs(NOTION_TOKEN, DATABASE_ID, myco_name)
                    st.metric(label=f"Notion ({myco_name})", value=n_count)
                else:
                    st.metric(label="Notion", value="--", help="Nom d'utilisateur non défini")
            else:
                st.metric(label="Notion", value="Déconnecté", delta_color="inverse")
        
        # Stat 3: User Role / Status -> Last Fongarium
        with st_col3:
             # Logic: Get prefix from session. If set, query Notion.
             user_info = st.session_state.get('user_info', {})
             prefix = user_info.get("fongarium_prefix")
             
             if prefix:
                 last_fong, next_fong = get_last_fongarium_number_v2(NOTION_TOKEN, DATABASE_ID, st.session_state.username, prefix)
                 if last_fong:
                     delta_msg = f"Suivant: {next_fong}" if next_fong else "Suivant: +1"
                     st.metric(label="Fongarium (Dernier)", value=last_fong, delta=delta_msg)
                 else:
                     st.metric(label="Fongarium", value="Aucun", help=f"Aucune entrée trouvée avec le préfixe {prefix}")
             else:
                 st.metric(label="Fongarium", value="Non configuré", help="Configurez votre préfixe dans 'Mon Profil'")
            
        st.divider()

    # --- INTERFACE (Tabs) ---
    tab1, tab2, tab3, tab4 = st.tabs(["🔎 Recherche & Filtres (iNat Style)", "🔢 Par Liste d'IDs", "🏷️ Étiquettes", "📚 Explorer Notion"])
    params = {}
    run_search = False
    import_list = [] # Will hold IDs or Obs to import
    
    with tab3:        
        # Check if we have selected observations
        # We need "visible_obs" accessible here, but currently it's computed later in the script (lines 550+).
        # OR we rely on st.session_state.selection_states AND st.session_state.search_results.
        
        selected_ids = [oid for oid, is_sel in st.session_state.selection_states.items() if is_sel]
        
        if not st.session_state.search_results:
             st.info("💡 Faites d'abord une recherche pour sélectionner des observations.")
        elif not selected_ids:
             st.warning("⚠️ Aucune observation sélectionnée. Cochez des cases dans l'onglet Résultats.")
        else:
             # Match IDs to actual Obs objects
             # Optimization: Create a dict map
             obs_map = {o['id']: o for o in st.session_state.search_results}
             
             # Filter only those present in search results (safety)
             valid_ids = [oid for oid in selected_ids if oid in obs_map]
             selected_obs_objects = [obs_map[oid] for oid in valid_ids]
             
             count = len(selected_obs_objects)
             st.success(f"✅ {count} observation(s) prête(s) pour l'impression.")

             with st.form("label_config"):
                 c_lbl_1, c_lbl_2 = st.columns(2)
                 title_input = c_lbl_1.text_input("Titre de l'étiquette", value="Fongarium Personnel")
                 include_coords = c_lbl_2.checkbox("Inclure Coordonnées GPS", value=True)
                 
                 submitted = st.form_submit_button("Générer PDF 📄", type="primary")
                 
             if submitted:
                  # Prepare Options
                  label_options = {
                      "title": title_input,
                      "include_coords": include_coords
                  }
                  
                  try:
                      with st.spinner("Génération..."):
                          pdf_data = generate_label_pdf(selected_obs_objects, label_options)
                      
                      st.balloons()
                      st.success("PDF Généré avec succès !")
                      st.download_button(
                          label="📥 Télécharger le PDF",
                          data=pdf_data,
                          file_name="etiquettes_inat.pdf",
                          mime="application/pdf"
                      )
                  except Exception as e:
                      st.error(f"Erreur lors de la génération : {e}")

with tab4:
    with st.container(border=True):
        st.markdown("### 📚 Explorateur de Base de Données Notion")
        st.caption("Visualisez les dernières entrées de votre base Notion et générez des étiquettes directement.")
        
        c_notion_cols = st.columns([3, 1])
        if c_notion_cols[1].button("🔄 Actualiser Notion", type="primary"):
            st.rerun()

        if st.checkbox("🐞 Debug Notion"):
             st.write(f"Notion Lib: {notion}")
             st.write(f"Methods: {dir(notion.databases)}")
             try:
                 dbg_schema = notion.databases.retrieve(DATABASE_ID)
                 st.json(dbg_schema["properties"])
             except Exception as e:
                 st.error(f"Debug Error: {e}")

        # Fetch from Notion using direct HTTP to avoid library version issues
        if NOTION_TOKEN and DATABASE_ID:
            import requests # Ensure requests is imported
            
            headers = {
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": "2022-06-28", # Stable version
                "Content-Type": "application/json"
            }
            
            try:
                # 1. Fetch Schema (GET /v1/databases/{id})
                api_url_db = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
                resp_schema = requests.get(api_url_db, headers=headers)
                
                if resp_schema.status_code != 200:
                    st.error(f"Notion Error {resp_schema.status_code}: {resp_schema.text}")
                    props_schema = {}
                else:
                    db_info = resp_schema.json()
                    props_schema = db_info.get("properties", {})

                # Extract Select Options
                myco_options = []
                # Robust property finding
                myco_key = next((k for k in props_schema if "mycologue" in k.lower()), "Mycologue")
                if myco_key in props_schema and props_schema[myco_key]["type"] == "select":
                    myco_options = [opt["name"] for opt in props_schema[myco_key]["select"]["options"]]
                
                projet_options = []
                projet_key = next((k for k in props_schema if "projet" in k.lower() or "inventaire" in k.lower()), "Projet d'inventaire")
                
                if projet_key in props_schema and props_schema[projet_key]["type"] == "select":
                     projet_options = [opt["name"] for opt in props_schema[projet_key]["select"]["options"]]
                
                # 2. Filter Bar
                with st.expander("🔍 Filtres Notion Avancés", expanded=True):
                    f_col1, f_col2, f_col3 = st.columns(3)
                    
                    # Mycologue
                    sel_myco = f_col1.selectbox(f"Mycologue ({myco_key})", ["Tous"] + myco_options)
                    
                    # Projet
                    # Check Select OR Multi-Select OR Relation
                    projet_map = {} # Name -> ID (for relations)
                    
                    if projet_key in props_schema:
                        p_conf = props_schema[projet_key]
                        p_type = p_conf["type"]
                        
                        if p_type == "select":
                            projet_options = [opt["name"] for opt in p_conf["select"]["options"]]
                        elif p_type == "multi_select":
                            projet_options = [opt["name"] for opt in p_conf["multi_select"]["options"]]
                        elif p_type == "relation":
                            # It's a relation! We need to fetch the related database.
                            try:
                                rel_db_id = p_conf["relation"]["database_id"]
                                # Query the related DB to get Names (Titles)
                                # Only need Title and ID.
                                url_rel = f"https://api.notion.com/v1/databases/{rel_db_id}/query"
                                # Fetch all (or first 100)
                                resp_rel = requests.post(url_rel, headers=headers, json={"page_size": 100})
                                
                                if resp_rel.status_code == 200:
                                    results_rel = resp_rel.json().get("results", [])
                                    # Extract titles
                                    for r in results_rel:
                                        r_props = r["properties"]
                                        # Find Title prop
                                        title_txt = "Sans titre"
                                        for k, v in r_props.items():
                                            if v["type"] == "title" and v["title"]:
                                                title_txt = v["title"][0]["text"]["content"]
                                                break
                                        if title_txt:
                                            projet_options.append(title_txt)
                                            projet_map[title_txt] = r["id"] # Store ID for filter
                                    
                                    projet_options = sorted(list(set(projet_options)))
                                elif resp_rel.status_code == 404:
                                     st.warning(f"⚠️ **Accès refusé** à la base de données liée 'Projets' (ID: {rel_db_id}).\n\n"
                                                "L'intégration 'iNat Sync' doit être invitée sur cette base de données aussi (via le menu 'Connections' sur la page Notion des projets).")
                                else:
                                     st.error(f"Erreur chargement projets: {resp_rel.status_code} {resp_rel.text}")
                            except Exception as e:
                                st.warning(f"Exception chargement projets: {e}")

                    if projet_options:
                        sel_proj = f_col2.selectbox(f"Projet ({projet_key})", ["Tous"] + projet_options)
                    else:
                        sel_proj = f_col2.text_input(f"Projet ({projet_key})", placeholder="Recherche textuelle...")
                        
                    # Date Logic (Year / Month / Specific Range)
                    # We keep the old specific date input for precision, but add Year/Month for "Archives" style
                    
                    st.caption("Filtres Temporels")
                    ft_col1, ft_col2 = st.columns(2)
                    
                    # Generate Years (Current back to 2010)
                    import datetime
                    current_year = datetime.date.today().year
                    years_opt = [str(y) for y in range(current_year, 2009, -1)]
                    
                    sel_years = ft_col1.multiselect("Années", years_opt, placeholder="Toutes")
                    
                    months_map = {
                        "Janvier": 1, "Février": 2, "Mars": 3, "Avril": 4, "Mai": 5, "Juin": 6,
                        "Juillet": 7, "Août": 8, "Septembre": 9, "Octobre": 10, "Novembre": 11, "Décembre": 12
                    }
                    sel_months = ft_col2.multiselect("Mois", list(months_map.keys()), placeholder="Tous")
                    
                    # Specific Period (Fallback if no years selected? Or AND?)
                    # Let's keep it separate as "Specific Range"
                    with st.expander("📅 Date précise (Période)", expanded=False):
                        sel_date = st.date_input("Sélectionner une période", value=[], help="Laissez vide pour utiliser les filtres Années/Mois ci-dessus.")

                f_col4, f_col5 = st.columns(2)
                
                # iNat ID
                # Prioritize "URL Inaturalist", then "No Inat.", then "INAT"
                inat_candidates = ["URL Inaturalist", "No Inat.", "INAT", "No Inat"]
                inat_col_name = "URL Inaturalist"
                found_inat = False
                for cand in inat_candidates:
                    if cand in props_schema:
                        inat_col_name = cand
                        found_inat = True
                        break
                if not found_inat:
                     inat_col_name = next((k for k, v in props_schema.items() if ("inat" in k.lower() or "url" in k.lower()) and v["type"] != "checkbox"), "URL Inaturalist")
                
                sel_inat_id = f_col4.text_input(f"ID iNaturalist (via {inat_col_name})", placeholder="ex: 123456")
                
                # Fongarium
                fong_candidates = ["No° fongarium", "No fongarium", "Numéro fongarium", "Code fongarium"]
                fong_col_name = "No° fongarium"
                found_fong = False
                for cand in fong_candidates:
                    if cand in props_schema:
                        fong_col_name = cand
                        found_fong = True
                        break
                if not found_fong:
                     fong_col_name = next((k for k,v in props_schema.items() if "fongarium" in k.lower() and v["type"] not in ["checkbox", "formula"]), "No° fongarium")
                
                sel_fong = f_col5.text_input(f"No° Fongarium (via {fong_col_name})", placeholder="ex: MYCO-01")
                
                # Limit Selector
                st.divider()
                l_col1, l_col2 = st.columns([1, 4])
                limit_opts = [50, 100, 200, 500, "Tout (Lent)"]
                sel_limit = l_col1.selectbox("Nombre de résultats", limit_opts, index=0)
                
                # Calculate numeric limit
                max_fetch = 50
                if isinstance(sel_limit, int): max_fetch = sel_limit
                else: max_fetch = 999999 # Unlimited
                
                # 3. Build Filter Payload
                notion_filter = {"and": []}
                
                # Mycologue
                if sel_myco != "Tous":
                    notion_filter["and"].append({"property": myco_key, "select": {"equals": sel_myco}})
                
                # Projet
                if sel_proj and sel_proj != "Tous":
                    if projet_options:
                         p_type = props_schema[projet_key]["type"]
                         if p_type == "select":
                             notion_filter["and"].append({"property": projet_key, "select": {"equals": sel_proj}})
                         elif p_type == "multi_select":
                             notion_filter["and"].append({"property": projet_key, "multi_select": {"contains": sel_proj}})
                         elif p_type == "relation":
                             if sel_proj in projet_map:
                                 rel_id = projet_map[sel_proj]
                                 notion_filter["and"].append({"property": projet_key, "relation": {"contains": rel_id}})
                    elif projet_key in props_schema:
                         # Text Fallback
                         p_type = props_schema[projet_key]["type"]
                         if p_type == "select":
                              notion_filter["and"].append({"property": projet_key, "select": {"equals": sel_proj}})
                         elif p_type == "multi_select":
                              notion_filter["and"].append({"property": projet_key, "multi_select": {"contains": sel_proj}})
                         elif p_type == "rich_text":
                              notion_filter["and"].append({"property": projet_key, "rich_text": {"contains": sel_proj}})

                # Date Logic
                # 1. Specific Date (Priority)
                if sel_date:
                    if len(sel_date) == 1:
                         notion_filter["and"].append({"property": "Date", "date": {"equals": sel_date[0].isoformat()}})
                    elif len(sel_date) == 2:
                         start_d, end_d = sel_date
                         if start_d > end_d: start_d, end_d = end_d, start_d
                         notion_filter["and"].append({
                             "and": [
                                 {"property": "Date", "date": {"on_or_after": start_d.isoformat()}},
                                 {"property": "Date", "date": {"on_or_before": end_d.isoformat()}}
                             ]
                         })
                # 2. Years (API Optimization)
                elif sel_years:
                    # Construct an OR group for each year selected
                    # (Date >= YYYY-01-01 AND Date <= YYYY-12-31)
                    year_or_group = {"or": []}
                    for y in sel_years:
                        year_or_group["or"].append({
                            "and": [
                                {"property": "Date", "date": {"on_or_after": f"{y}-01-01"}},
                                {"property": "Date", "date": {"on_or_before": f"{y}-12-31"}}
                            ]
                        })
                    notion_filter["and"].append(year_or_group)
                
                # iNat ID (Multi)
                if sel_inat_id:
                     id_tokens = [t.strip() for t in sel_inat_id.replace(","," ").split() if t.strip()]
                     if id_tokens:
                         type_inat = props_schema.get(inat_col_name, {}).get("type", "url")
                         or_clause = {"or": []}
                         for t in id_tokens:
                             if type_inat == "url":
                                  or_clause["or"].append({"property": inat_col_name, "url": {"contains": t}})
                             elif type_inat == "number":
                                  try:
                                      val = int(t)
                                      or_clause["or"].append({"property": inat_col_name, "number": {"equals": val}})
                                  except: pass
                             else:
                                  or_clause["or"].append({"property": inat_col_name, "rich_text": {"contains": t}})
                         if or_clause["or"]:
                             notion_filter["and"].append(or_clause)

                # Fongarium (Multi)
                if sel_fong:
                    fong_tokens = [t.strip() for t in sel_fong.replace(","," ").split() if t.strip()]
                    if fong_tokens:
                        or_clause = {"or": []}
                        for t in fong_tokens:
                            or_clause["or"].append({"property": fong_col_name, "rich_text": {"contains": t}})
                        if or_clause["or"]:
                             notion_filter["and"].append(or_clause)

                # Query Loop (Optimized via Cache)
                # We need to handle the "Month Filter" logic which is Python-side.
                # To purely cache the extensive API call, we just fetch by Date/Year/ID/Matches
                # And apply Month filter after (fast).
                
                # We pass 'notion_filter["and"]' which is a list of clauses.
                all_results_raw = fetch_notion_data(NOTION_TOKEN, DATABASE_ID, notion_filter["and"], max_fetch)
                
                # POST-PROCESSING: Month Filter (Python Side)
                all_results = []
                if sel_months and not sel_date:
                     target_month_nums = [months_map[m] for m in sel_months]
                     for p in all_results_raw:
                        d_str = ""
                        if "Date" in p["properties"] and p["properties"]["Date"]["date"]:
                            d_str = p["properties"]["Date"]["date"]["start"]
                        
                        if d_str:
                            try:
                                m_num = int(d_str.split("-")[1])
                                if m_num in target_month_nums:
                                    all_results.append(p)
                            except: pass
                        else:
                             pass
                else:
                    all_results = all_results_raw
                
                if max_fetch > 100:
                    prog_text.empty() # Clear text (if it was used)
                
                rows_notion = []
                # Process results... (Use all_results)
                results = all_results # Mapping variable
                    
                for p in results:
                    props = p["properties"]
                    
                    # Helpers to extract text safely
                    def get_prop_text(p_dict):
                        if not p_dict: return ""
                        ptype = p_dict["type"]
                        if ptype == "title" and p_dict["title"]:
                            return p_dict["title"][0]["text"]["content"]
                        if ptype == "rich_text" and p_dict["rich_text"]:
                            return p_dict["rich_text"][0]["text"]["content"]
                        if ptype == "select" and p_dict["select"]:
                            return p_dict["select"]["name"]
                        if ptype == "date" and p_dict["date"]:
                            return p_dict["date"]["start"]
                        if ptype == "url":
                            return p_dict["url"]
                        if ptype == "number":
                            return str(p_dict["number"])
                        if ptype == "formula":
                            # Handle Formula (String or Number)
                            f_val = p_dict["formula"]
                            if f_val["type"] == "string": return f_val["string"]
                            if f_val["type"] == "number": return str(f_val["number"])
                        return ""

                    # Mapping based on fuzzy keys found earlier + Standard "Date"
                    taxon = "Inconnu"
                    # Find Title Prop
                    title_key = next((k for k,v in props.items() if v["type"] == "title"), "Titre")
                    if title_key in props: taxon = get_prop_text(props[title_key]) or "Sans Titre"
                    
                    date_obs = "Inconnue"
                    if "Date" in props: date_obs = get_prop_text(props["Date"])
                    
                    place = "Inconnu"
                    # Look for "Repère" or "Lieu"
                    place_key = next((k for k in props if "repère" in k.lower() or "lieu" in k.lower()), "Repère")
                    if place_key in props: place = get_prop_text(props[place_key])
                    
                    user = ""
                    if myco_key in props: user = get_prop_text(props[myco_key])
                    
                    # Extra Fields Extraction
                    # 1. Project (Projet d'inventaire)
                    project = ""
                    if projet_key in props: project = get_prop_text(props[projet_key])
                    
                    # 2. Fongarium
                    fongarium = ""
                    if fong_col_name in props: fongarium = get_prop_text(props[fong_col_name])
                    
                    # 3. iNat ID (Formatted)
                    # Try to find "No Inat." or candidates
                    inat_id_val = ""
                    # We already have 'inat_col_name' from the filter section logic
                    # But strictly speaking 'inat_col_name' might be the URL column used for searching.
                    # User specifically wants "No Inat." (Formula).
                    # Let's try to find a formula column named variants of "No Inat"
                    nid_key = next((k for k,v in props.items() if ("no" in k.lower() and "inat" in k.lower()) and v["type"] == "formula"), "")
                    
                    if nid_key and nid_key in props:
                        inat_id_val = get_prop_text(props[nid_key])
                    elif inat_col_name in props and props[inat_col_name]["type"] == "formula":
                        # If the filter column itself was the formula
                        inat_id_val = get_prop_text(props[inat_col_name])
                    
                    # 4. Habitat (Relation)
                    raw_habitat = []
                    hab_key = next((k for k in props if "habitat" in k.lower()), "Habitat")
                    if hab_key in props and props[hab_key]["type"] == "relation":
                        raw_habitat = [r["id"] for r in props[hab_key]["relation"]]
                        
                    # 5. Substrate (Relation)
                    raw_substrate = []
                    sub_key = next((k for k in props if "substra" in k.lower()), "Substrat")
                    if sub_key in props and props[sub_key]["type"] == "relation":
                            raw_substrate = [r["id"] for r in props[sub_key]["relation"]]

                    # 6. GPS (Lat/Long)
                    # Prioritize explicit "sexadécimal" columns as requested
                    lat_key = "Latitude (sexadécimal)"
                    if lat_key not in props:
                        lat_key = next((k for k in props if "lat" in k.lower() and "re" not in k.lower()), "Latitude")
                        
                    lng_key = "Longitude (sexadécimal)"
                    if lng_key not in props:
                            lng_key = next((k for k in props if "long" in k.lower()), "Longitude")
                    
                    gps_val = ""
                    lat_val = ""
                    lng_val = ""
                    
                    if lat_key in props: lat_val = get_prop_text(props[lat_key])
                    if lng_key in props: lng_val = get_prop_text(props[lng_key])
                    
                    if lat_val and lng_val:
                        gps_val = f"{lat_val}, {lng_val}"

                    notion_id = p["id"]
                    page_url = p["url"]
                    
                    rows_notion.append({
                        "id": notion_id,
                        "Taxon": taxon,
                        "ID iNaturalist": inat_id_val,
                        "Date": date_obs,
                        "Lieu": place,
                        "Mycologue": user,
                        "custom_url": page_url,
                        "Projet": project,
                        "Fongarium": fongarium,
                        "raw_habitat": raw_habitat,
                        "raw_substrate": raw_substrate,
                        "GPS": gps_val
                    })
                
                if rows_notion:
                    df_notion = pd.DataFrame(rows_notion)
                    # Add Selection Column
                    df_notion.insert(0, "Imprimer", False)
                    
                    st.write(f"**{len(rows_notion)} résultats trouvés.**")
                    
                    # Data Editor for Selection
                    edited_df = st.data_editor(
                        df_notion,
                        column_config={
                            "Imprimer": st.column_config.CheckboxColumn("🖨️", help="Cochez pour générer une étiquette", default=False),
                            "custom_url": st.column_config.LinkColumn("Lien Notion"),
                            "id": None # Hide ID
                        },
                        key="notion_editor_req",
                        hide_index=True,
                        use_container_width=True,
                        disabled=["Taxon", "Date", "Lieu", "Mycologue", "custom_url"]
                    )
                    
                    # Process Selection
                    selected_rows = edited_df[edited_df["Imprimer"]]
                    
                    if not selected_rows.empty:
                        st.divider()
                        st.markdown("#### 🖨️ Impression")
                        
                        obs_for_labels = []
                        
                        # Cache for Relation Names to avoid repeated API calls
                        relation_cache = {}
                        
                        def get_relation_name(page_id):
                            if not page_id: return ""
                            if page_id in relation_cache: return relation_cache[page_id]
                            
                            try:
                                r_url = f"https://api.notion.com/v1/pages/{page_id}"
                                r_resp = requests.get(r_url, headers=headers)
                                if r_resp.status_code == 200:
                                    r_props = r_resp.json().get("properties", {})
                                    # Try to find Name/Title
                                    # Usually standard title property
                                    for k, v in r_props.items():
                                        if v["type"] == "title" and v["title"]:
                                            name = v["title"][0]["text"]["content"]
                                            relation_cache[page_id] = name
                                            return name
                                return "Inconnu"
                            except:
                                return "Erreur"

                        # Progress bar for resolving relations if many selected
                        resolve_prog = st.empty()
                        
                        c_gen_1, c_gen_2 = st.columns(2)
                        n_title = c_gen_1.text_input("Titre Étiquette", value="Fongarium (Notion)", key="notion_lbl_title_req")
                        
                        if st.button(f"Générer PDF ({len(selected_rows)})", type="primary", key="btn_notion_pdf_req"):
                            try:
                                with st.spinner("Préparation des données (Résolution des relations Notion)..."):
                                    for idx, row in selected_rows.iterrows():
                                         # Resolve Relations here
                                         hab_name = ""
                                         if row.get("raw_habitat"):
                                             # Handle single or multiple? Take first.
                                             # row["raw_habitat"] should be list of IDs
                                             ids = row["raw_habitat"]
                                             if isinstance(ids, list) and ids:
                                                 hab_name = get_relation_name(ids[0])
                                         
                                         sub_name = ""
                                         if row.get("raw_substrate"):
                                             ids = row["raw_substrate"]
                                             if isinstance(ids, list) and ids:
                                                 sub_name = get_relation_name(ids[0])

                                         obs = {
                                             "id": row["id"],
                                             "taxon": {"name": row["Taxon"]},
                                             "observed_on_string": row["Date"],
                                             "place_guess": row["Lieu"],
                                             "user": {"name": row["Mycologue"]},
                                             "custom_url": row["custom_url"],
                                             "project": row.get("Projet", ""),
                                             "fongarium_no": row.get("Fongarium", ""),
                                             "habitat": hab_name,
                                             "substrate": sub_name,
                                             "ID iNaturalist": row.get("ID iNaturalist", ""),
                                             "GPS": row.get("GPS", "")
                                         }
                                         obs_for_labels.append(obs)
                                
                                opts = {"title": n_title, "include_coords": False}
                                pdf_bytes = generate_label_pdf(obs_for_labels, opts)
                                st.session_state['notion_pdf'] = pdf_bytes
                                st.success("PDF prêt !")
                            except Exception as ex:
                                st.error(f"Erreur PDF: {ex}")
                        
                        if 'notion_pdf' in st.session_state:
                             st.download_button("📥 Télécharger", st.session_state['notion_pdf'], "etiquettes_notion.pdf", "application/pdf")

                else:
                    if resp_query.status_code == 200:
                        st.info("Aucun résultat pour cette recherche.")
                    
            except Exception as e:
                 st.error(f"Erreur Notion Load: {e}")

                    
            except Exception as e:
                 st.error(f"Erreur Notion Load: {e}")
        else:
             st.warning("Veuillez configurer les secrets Notion.")



with tab1:
    with st.container(border=True):
        st.markdown("### 🌪️ Filtres de Recherche")
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
                    # st.rerun() removed to avoid "Bad message format" in Streamlit 1.40+
                    pass
            else:
                # Default fallback if empty? User requested selection.
                # If empty, maybe use default_user if provided? 
                # Logic below uses selected_users if present, else default?
                # Let's keep it clean: params will use this list. 
                # If list empty, maybe params['user_id'] is empty (all users)? Or default?
                if st.session_state.inat_username and not st.session_state.selected_users:
                     # Pre-populate default if nothing selected yet?
                     # Risky if they want "All". 
                     # Let's just show "Aucun utilisateur filtré (Tout le monde)"
                     st.info("Aucun filtre utilisateur (Tout le monde)")

            # Compatibility with downstream logic
            # function will join st.session_state.selected_users
            
             # --- TAXON SEARCH ENGINE ---
            # --- TAXON SEARCH ENGINE ---
            st.markdown("**🍄 Groupe Taxonomique**")
            
            # 1. ICONIC TAXA DEFINITION (Maps to User Screenshot)
            # ID Source: https://www.inaturalist.org/pages/api+reference#get-taxa
            ICONIC_TAXA = {
                "Oiseaux 🐦": 3,
                "Amphibiens 🐸": 20978,
                "Reptiles 🐍": 26036,
                "Mammifères 🐀": 40151,
                "Poissons 🐟": 47178, # Actinopterygii (Ray-finned fishes) - broadly "fish"
                "Mollusques 🐌": 47115,
                "Arachnides 🕷️": 47119,
                "Insectes 🐞": 47158,
                "Plantes 🌿": 47126,
                "Champignons 🍄": 47170,
                "Protozoaires 🦠": 47686,
                "Inconnu ❓": "unknown" 
            }
            
            # Options for pills
            pill_options = list(ICONIC_TAXA.keys())
            
            # Default to Fungi
            default_selection = ["Champignons 🍄"]
            
            # Selection (Multi)
            selected_icons = st.pills(
                "Groupe",
                options=pill_options,
                default=default_selection,
                selection_mode="multi",
                label_visibility="collapsed",
                key="taxon_pills"
            )
            
            # Determine Base ID from Pills
            taxon_id = None
            if selected_icons:
                ids = []
                for icon in selected_icons:
                    tid = ICONIC_TAXA.get(icon)
                    if tid and tid != "unknown":
                        ids.append(str(tid))
                
                if ids:
                    taxon_id = ",".join(ids) # iNat API accepts comma separated IDs
            
            # 2. OPTIONAL: Specific Text Override
            with st.expander("🔍 Recherche précise (Espèce/Genre)"):
                taxon_query = st.text_input("Nom scientifique ou commun", placeholder="ex: Canis lupus")
                if taxon_query:
                    try:
                        taxa = get_taxa_autocomplete(q=taxon_query, per_page=10)
                        if taxa['results']:
                            taxon_options = {f"{t['name']} ({t.get('preferred_common_name', 'No common name')})": t['id'] for t in taxa['results']}
                            selected_taxon_name = st.selectbox("Sélectionner:", options=taxon_options.keys())
                            # OVERRIDE Pill ID
                            taxon_id = taxon_options[selected_taxon_name]
                            st.success(f"Filtre actif : {selected_taxon_name} (ID: {taxon_id})")
                        else:
                            st.warning("Aucun taxon trouvé.")
                    except Exception as e:
                        st.error(f"Erreur recherche: {e}")
                elif not taxon_id:
                    st.caption("Filtre actuel : Aucun (Tout afficher)")
                else:
                    st.caption(f"Filtre actuel : {selected_icons} (IDs: {taxon_id})")

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
            c_q1, c_q2, c_q3, c_q4 = st.columns(4)
            today = date.today()
            
            if c_q1.button("Auj.", type="secondary", use_container_width=True, help="Aujourd'hui"):
                st.session_state.d_start = today
                st.session_state.d_end = today
                st.rerun()
                
            if c_q2.button("Sem.", type="secondary", use_container_width=True, help="7 derniers jours"):
                st.session_state.d_start = today - timedelta(days=6)
                st.session_state.d_end = today
                st.rerun()

            if c_q3.button("2 Sem.", type="secondary", use_container_width=True, help="14 derniers jours"):
                st.session_state.d_start = today - timedelta(days=13)
                st.session_state.d_end = today
                st.rerun()
                
            if c_q4.button("Mois", type="secondary", use_container_width=True, help="Depuis le 1er du mois"):
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
                            # No rerun needed, button already triggers it
                            pass
                    
                    if st.button("🗑️ Effacer tout", type="secondary"):
                        st.session_state.custom_dates = []
                        st.rerun()
                else:
                    st.info("Aucune date ajoutée.")

        st.divider()

        # Limit Selection
        c_search, c_limit = st.columns([3, 1])
        # Changed label to distinguish from table filter
        # Changed default to 200 (index 2) to show more results by default
        limit_option = c_limit.selectbox("Max à récupérer (iNat)", [50, 100, 200, 500, 1000, "Tout (Attention !)"], index=2)
        
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
            if not st.session_state.selected_users:
                 if default_user:
                     user_list = [default_user]
                 
                 # Fallback: If user typed in "Add User" but didn't click Plus, let's try to use it?
                 # BUT only if they didn't set a default_user or if they rely on text input.
                 # Actually, if new_user is present, it's a strong signal they want it.
                 if new_user and new_user not in user_list:
                      # Use the typed user instead of (or with?) default? 
                      # Usually "Add User" implies override. 
                      # Let's add it to the search list.
                      user_list = [new_user] 

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
                "per_page": 200 # Request max allowed per page
            }
            run_search = True

with tab2:
    with st.container(border=True):
        ids_input = st.text_area("IDs (séparés par virgules ou sauts de ligne)")
        if st.button("🔎 Rechercher IDs", type="primary"):
            # Replace newlines with commas, then split
            normalized_input = ids_input.replace('\n', ',')
            id_list = [x.strip() for x in normalized_input.split(',') if x.strip().isdigit()]
            if id_list:
                params = {"id": id_list}
                fetch_limit = len(id_list) # Use list length as limit
                run_search = True

# --- SEARCH EXECUTION ---
if run_search:
    with st.spinner("Recherche sur iNaturalist..."):
        try:
            collected = []
            total_available = 0
            
            if date_mode == "Multi-dates" and st.session_state.custom_dates:
                 # Logic for multi-date (complex total)
                 # We sum up totals? Or just show what we have.
                 for d in st.session_state.custom_dates:
                    p = params.copy()
                    p['on'] = d 
                    p.pop('d1', None); p.pop('d2', None)
                    
                    # Fetch batch
                    p['page'] = 1
                    p['per_page'] = min(200, fetch_limit)
                    resp = get_observations(**p)
                    total_available += resp.get('total_results', 0)
                    
                    # Pagination logic (simplified for multi-date: just grab up to limit per date?)
                    # User asked for "Absolute result". 
                    # If I sum total_results of all dates, that is correct.
                    # Start with first batch
                    batch = resp['results']
                    collected.extend(batch)
                    
                    # Add more pages if needed? (Skipping for brevity/speed unless requested)
                    # If fetch_limit > 200, we might need loop.
                    while len(batch) == 200 and len(collected) < fetch_limit:
                        p['page'] += 1
                        batch = get_observations(**p)['results']
                        collected.extend(batch)
                        if not batch: break
            else:
                 # Standard Search (Single flow)
                 page = 1
                 while len(collected) < fetch_limit:
                     remaining = fetch_limit - len(collected)
                     p_size = min(200, remaining)
                     params['page'] = page
                     params['per_page'] = p_size
                     
                     resp = get_observations(**params)
                     if page == 1:
                         total_available = resp.get('total_results', 0)
                         
                     batch = resp['results']
                     if not batch: break
                     
                     collected.extend(batch)
                     if len(batch) < p_size: break
                     page += 1
            
            results = collected
            
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
            
            # --- UNIFIED DATAFRAME INIT ---
            # Create the master DF for the new unified editor
            # Columns: [Import?] [ID] [Taxon] [Date] [Lieu] [Mycologue] [Collection?] [No° Fongarium] [Link]
            
            u_data = []
            for r in unique_results:
                # Helper for Date extraction
                d_val = r.get('time_observed_at')
                date_str = str(d_val)[:10] if d_val else (str(r.get('observed_on') or "")[:10] or "Inconnue")
                
                # Helper for User
                user_name = r.get('user', {}).get('login') or "Inconnu"
                
                # Helper for Link
                # We can't put a functional link column easily in basic data_editor without using LinkColumn config.
                # We will store the full URL and format it in column_config.
                
                # Helper for Tags
                tags = r.get('tags', []) 
                tag_list = []
                if tags:
                    for t in tags:
                        if isinstance(t, dict): tag_list.append(t.get('tag', ''))
                        elif isinstance(t, str): tag_list.append(t)
                        else: tag_list.append(str(t))
                tag_str = ", ".join(tag_list)
                
                # Helper for GPS
                loc = r.get('location')
                gps_txt = ""
                if loc:
                     try:
                         # location is often "lat,lon" string or [lat, lon]
                         if isinstance(loc, str): gps_txt = loc
                         elif isinstance(loc, list): gps_txt = f"{loc[0]}, {loc[1]}"
                     except: gps_txt = "Oui"
                
                # Helper for Description
                desc = r.get('description', '') or ""

                u_data.append({
                    "Import?": True,
                    "ID": str(r['id']), 
                    "Taxon": r.get('taxon', {}).get('name') or "Inconnu",
                    "Date": date_str,
                    "Lieu": r.get('place_guess') or "Inconnu",
                    "Mycologue": user_name,
                    "Tags": tag_str,
                    "GPS": gps_txt,
                    "Description": desc,
                    "Collection": False,
                    "No° Fongarium": "",
                    "Lien": r.get('uri') or f"https://www.inaturalist.org/observations/{r['id']}"
                })
            
            st.session_state.main_import_df = pd.DataFrame(u_data)
            st.session_state.editor_key_version = 0 # Reset editor key
            
            st.session_state.total_results_count = total_available # NEW: Store total
            
            st.session_state.show_selection = True
            if not unique_results:
                st.warning("Aucune observation trouvée.")
        except Exception as e:
            st.error(f"Erreur iNaturalist : {e}")
            st.session_state.search_results = []
            st.session_state.main_import_df = pd.DataFrame() # Empty fallback



# --- UNIFIED TABLE INTERFACE ---
if 'main_import_df' in st.session_state and not st.session_state.main_import_df.empty:
    st.divider()
    
    # 1. FILTERS & CONTROLS
    c_title, c_stats = st.columns([2, 2])
    
    # Calculate unique dates for filter
    df_main = st.session_state.main_import_df
    all_dates = sorted(df_main['Date'].unique().tolist(), reverse=True)
    
    # Limit Options
    limit_options = [50, 100, 200, "Tout"]
    
    with c_title:
        st.subheader(f"📋 Aperçu d'importation (Inaturalist) ({len(df_main)} obs)")
    
    # Filter Widgets
    col_date, col_limit = st.columns([3, 1])
    
    # Date Filter (Pills)
    selected_dates = col_date.pills(
        "Filtrer par date",
        options=all_dates,
        selection_mode="multi",
        default=[]
    )
    
    # Limit Filter
    # Default to "Tout" (Index 3) to show all fetched results immediately
    selected_limit = col_limit.selectbox("Afficher", options=limit_options, index=3)
    
    # Apply Filters
    df_filtered = df_main.copy()
    if selected_dates:
        df_filtered = df_filtered[df_filtered['Date'].isin(selected_dates)]
    
    # Slice for Display (Limit)
    if selected_limit != "Tout":
         df_display = df_filtered.head(int(selected_limit))
    else:
         df_display = df_filtered

    # Update Stats Display
    # Use metric or markdown to bold Total
    c_stats.markdown(f"**Total Extrait : {len(df_main)}** | Filtré : {len(df_filtered)} | Affiché : {len(df_display)}")

    # 2. BULK ACTIONS
    col_bulk_l, col_bulk_r = st.columns([1, 1])
    if col_bulk_l.button("✅ Tout cocher (Visible)", help="Coche 'Importer' pour toutes les lignes affichées"):
        # Update Master DF based on Visible Indices
        visible_indices = df_display.index
        st.session_state.main_import_df.loc[visible_indices, "Import?"] = True
        st.session_state.editor_key_version = st.session_state.get('editor_key_version', 0) + 1
        st.rerun()
        
    if col_bulk_r.button("🚫 Tout décocher (Visible)", help="Décoche 'Importer' pour toutes les lignes affichées"):
        visible_indices = df_display.index
        st.session_state.main_import_df.loc[visible_indices, "Import?"] = False
        st.session_state.editor_key_version = st.session_state.get('editor_key_version', 0) + 1
        st.rerun()

    # --- MAGIC BUTTON (Unified) ---
    col_magic, col_space = st.columns([1, 2])
    if col_magic.button("🪄 Générer les numéros", help="Remplit 'No° Fongarium' pour les lignes cochées 'Collection' (visible uniquement)"):
         # 1. SYNC STATE FIRST (Capture pending edits from widget before action)
         current_key = f"main_editor_{st.session_state.get('editor_key_version', 0)}"
         editor_state = st.session_state.get(current_key, {})
         edited_rows = editor_state.get("edited_rows", {})
         
         # Apply edits (Collection checkbox mainly) BEFORE logic
         # CRITICAL: If we filter, 0-based index in editor refers to 0-th row of df_display.
         # We must map 0 -> df_display.index[0].
         
         user_info = st.session_state.get('user_info', {})
         prefix = user_info.get("fongarium_prefix")
         
         # Apply edits first
         for row_idx_str, changes in edited_rows.items():
              try:
                  row_pos = int(row_idx_str)
                  # Start ID in Master DF
                  if row_pos < len(df_display):
                      real_index = df_display.index[row_pos]
                      for col in ["Collection", "Import?", "No° Fongarium"]:
                          if col in changes:
                              st.session_state.main_import_df.at[real_index, col] = changes[col]
              except Exception as e:
                  pass

         if not prefix: 
             st.error("Configurez votre préfixe dans 'Mon Profil' !")
         else:
            with st.spinner("Calcul..."):
                 last_f, next_start = get_last_fongarium_number_v2(NOTION_TOKEN, DATABASE_ID, st.session_state.username, prefix)
                 
                 if not next_start:
                     next_start = f"{prefix}0001"
                 
                 import re
                 match = re.search(r"(\d+)$", next_start)
                 if match:
                     current_num = int(match.group(1))
                     num_len = len(match.group(1))
                     current_prefix = next_start[:match.start()]
                 else:
                     current_num = 1
                     num_len = 4
                     current_prefix = prefix

                 processed_count = 0
                 # Iterate on visible indices
                 target_indices = df_display.index
                 
                 for idx in target_indices:
                     row = st.session_state.main_import_df.loc[idx]
                     if row["Collection"] and not row["No° Fongarium"]:
                         code = f"{current_prefix}{current_num:0{num_len}d}"
                         st.session_state.main_import_df.at[idx, "No° Fongarium"] = code
                         current_num += 1
                         processed_count += 1
                 
                 st.success(f"{processed_count} numéros générés !")
                 st.session_state.editor_key_version = st.session_state.get('editor_key_version', 0) + 1
                 st.rerun()

    # --- DATA EDITOR ---
    if 'editor_key_version' not in st.session_state: st.session_state.editor_key_version = 0
    
    # We must reset the dataframe to be displayed to reflect updates from buttons/generations
    # Re-calc df_display from fresh master state
    df_filtered_fresh = st.session_state.main_import_df.copy()
    if selected_dates:
         df_filtered_fresh = df_filtered_fresh[df_filtered_fresh['Date'].isin(selected_dates)]
    if selected_limit != "Tout":
         df_display_fresh = df_filtered_fresh.head(int(selected_limit))
    else:
         df_display_fresh = df_filtered_fresh
         
    edited_df = st.data_editor(
        df_display_fresh,
        key=f"main_editor_{st.session_state.editor_key_version}",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Import?": st.column_config.CheckboxColumn("Importer?", width="small", default=True),
            "ID": st.column_config.TextColumn("ID", disabled=True, width="small"),
            "Taxon": st.column_config.TextColumn("Taxon", disabled=True),
            "Date": st.column_config.TextColumn("Date", disabled=True, width="small"),
            "Lieu": st.column_config.TextColumn("Lieu", disabled=True),
            "Mycologue": st.column_config.TextColumn("User", disabled=True, width="medium"),
            "Tags": st.column_config.TextColumn("Tags", disabled=True, width="medium"),
            "GPS": st.column_config.TextColumn("GPS", disabled=True, width="medium"),
            "Description": st.column_config.TextColumn("Description", disabled=True, width="large"),
            "Collection": st.column_config.CheckboxColumn("Collection?", default=False, width="small"),
            "No° Fongarium": st.column_config.TextColumn("No° Fongarium", width="medium"),
            "Lien": st.column_config.LinkColumn("Lien", display_text="Ouvrir", width="small")
        },
        disabled=["ID", "Taxon", "Date", "Lieu", "Mycologue", "Tags", "GPS", "Description", "Lien"]
    )
    
    # CRITICAL: SYNC EDITS BACK TO MASTER
    # `edited_df` contains the state of the editor. 
    # Because we are filtering, `edited_df` is a subset. 
    # We must update `main_import_df` using the indices from `edited_df`.
    # Since `df_display` preserved the original indices, `edited_df` (which is returned by data_editor) 
    # SHOULD preserve them IF we don't mess it up. 
    # Wait, `edited_df` is a Pandas DataFrame returning the data in the editor.
    # If the input had an index, the output HAS THE SAME INDEX.
    # So we can just use `update`.
    
    if not edited_df.equals(df_display_fresh):
        # Update modified rows only to save perf? Or just update all common indices?
        # main_import_df.update(edited_df) overwrites intersecting cells.
        st.session_state.main_import_df.update(edited_df)
        # Note: update() modifies in place.

    # --- IMPORT BUTTON ---
    col_dup, col_imp = st.columns([1, 1])
    
    # We need to map `main_import_df` (Master) where Import?=True for the final action
    if col_imp.button("📤 Importer vers Notion", type="primary"):
        # Filter Master, not just visible
        master_df = st.session_state.main_import_df
        to_import_df = master_df[master_df["Import?"] == True]
        
        if to_import_df.empty:
            st.warning("Aucune observation cochée pour l'import.")
        elif NOTION_TOKEN and DATABASE_ID:
            # Resolve Notion Fongarium Column Name (Dynamic)
            import_props_schema = props_schema if 'props_schema' in locals() else {}
            
            fong_col_imp_name = "No° fongarium"
            
            if import_props_schema:
                fong_candidates = ["No° fongarium", "No fongarium", "Numéro fongarium", "Code fongarium"]
                for cand in fong_candidates:
                    if cand in import_props_schema:
                        fong_col_imp_name = cand
                        break
                    if fong_col_imp_name == "No° fongarium":
                         fong_col_imp_name = next((k for k,v in import_props_schema.items() if "fongarium" in k.lower() and v["type"] not in ["checkbox", "formula"]), "No° fongarium")
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Map back to full objects for details not in table (like Photos, Desc, raw Coords)
            # We assume search_results is still available and parallel.
            # Ideally we should have stored everything in DF, but Objects/Lists in DF are tricky in Editor.
            # So looking up by ID in search_results is safer.
            obs_map = {str(obs['id']): obs for obs in st.session_state.search_results}
            
            total_imp = len(to_import_df)
            for i, (idx, row) in enumerate(to_import_df.iterrows()):
                obs_id = str(row["ID"])
                obs = obs_map.get(obs_id)
                if not obs: continue 
                
                sci_name = row["Taxon"]
                status_text.text(f"Importation de {sci_name} ({i+1}/{total_imp})...")
                
                # --- DATA EXTRACTION & MAPPING ---
                user_name = obs.get('user', {}).get('login') or "Inconnu"
                # User Override from Row? (Mycologue column is disabled, so use source)
                
                observed_on = obs.get('time_observed_at')
                date_iso = observed_on.isoformat() if observed_on else None
                
                obs_url = obs.get('uri')
                
                tags = obs.get('tags', []) 
                tag_string = ""
                if tags:
                    extracted_tags = []
                    for t in tags:
                        if isinstance(t, dict): extracted_tags.append(t.get('tag', ''))
                        elif isinstance(t, str): extracted_tags.append(t)
                        else: extracted_tags.append(str(t))
                    tag_string = ", ".join(filter(None, extracted_tags))

                fong_code = row["No° Fongarium"]
                
                photos = obs.get('photos', [])
                cover_url = photos[0]['url'].replace("square", "medium") if photos else None
                first_photo_url = photos[0]['url'].replace("square", "original") if photos else None

                # Children
                children = []
                if len(photos) > 1:
                    children.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Galerie Photo"}}]}})
                    for p in photos:
                        children.append({
                            "object": "block", 
                            "type": "image", 
                            "image": {"type": "external", "external": {"url": p['url'].replace("square", "large")}}
                        })

                # Props
                props = {}
                props["Titre"] = {"title": [{"text": {"content": sci_name}}]}
                if date_iso: props["Date"] = {"date": {"start": date_iso}}
                if user_name: props["Mycologue"] = {"select": {"name": user_name}}
                if obs_url: props["URL Inaturalist"] = {"url": obs_url}
                if first_photo_url: props["Photo Inat"] = {"url": first_photo_url}
                
                if fong_code:
                     props[fong_col_imp_name] = {"rich_text": [{"text": {"content": str(fong_code)}}]}
                elif tag_string: 
                     props[fong_col_imp_name] = {"rich_text": [{"text": {"content": tag_string}}]}
                
                description = obs.get('description', '')
                if description: props["Description rapide"] = {"rich_text": [{"text": {"content": description[:2000]}}]}
                
                place_guess = obs.get('place_guess', '')
                if place_guess: props["Repère"] = {"rich_text": [{"text": {"content": place_guess}}]}
                
                # Coords
                lat = None; lon = None
                coords = obs.get('location')
                if coords:
                    try:
                        if isinstance(coords, str): parts = coords.split(','); lat = float(parts[0]); lon = float(parts[1])
                        elif isinstance(coords, list) and len(coords) >= 2: lat = float(coords[0]); lon = float(coords[1])
                    except: pass
                if lat: props["Latitude (sexadécimal)"] = {"rich_text": [{"text": {"content": str(lat)}}]}
                if lon: props["Longitude (sexadécimal)"] = {"rich_text": [{"text": {"content": str(lon)}}]}

                # SEND
                try:
                    import re
                    clean_id_imp = re.sub(r'[^a-fA-F0-9]', '', DATABASE_ID)
                    if len(clean_id_imp) == 32:
                        fmt_db_id = f"{clean_id_imp[:8]}-{clean_id_imp[8:12]}-{clean_id_imp[12:16]}-{clean_id_imp[16:20]}-{clean_id_imp[20:]}"
                    else: fmt_db_id = clean_id_imp
                        
                    new_page = notion.pages.create(
                        parent={"database_id": fmt_db_id, "type": "database_id"},
                        properties=props,
                        children=children,
                        cover={"external": {"url": cover_url}} if cover_url else None
                    )
                    
                    # QR Code Logic
                    page_url = new_page.get('url')
                    page_id = new_page.get('id')
                    if page_url and page_id:
                        qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={page_url}"
                        try:
                            notion.pages.update(page_id=page_id, properties={"Code QR": {"files": [{"name": "notion_qr.png", "type": "external", "external": {"url": qr_api_url}}]}})
                        except: pass

                except Exception as e:
                    st.warning(f"Erreur Notion sur {sci_name}: {e}")
                
                progress_bar.progress((i + 1) / total_imp)
            
            status_text.text("✅ Importation terminée avec succès !")
            st.success("Import terminé.")
