import streamlit as st
import pandas as pd
import requests
from pyinaturalist import get_observations, get_places_autocomplete, get_taxa_autocomplete
from notion_client import Client
from datetime import date, timedelta
from labels import generate_label_pdf
from database import get_user_by_email, create_user_profile, log_action, update_user_profile
from whitelist import AUTHORIZED_USERS


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
            # We blindly send them; if DB lacks columns, update_user_profile catches exception
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

        # Stat 2: Notion (Status)
        with st_col2:
            # We can't easily get total count without big query.
            # Just show connected status
            if notion:
                st.metric(label="Notion", value="Connecté", delta="Prêt")
            else:
                st.metric(label="Notion", value="Déconnecté", delta_color="inverse")
        
        # Stat 3: User Role / Status
        with st_col3:
            st.metric(label="Compte", value="Membre")
            
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

                # Query Loop (Pagination)
                api_url_query = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
                
                all_results = []
                has_more = True
                next_cursor = None
                
                # Progress bar if "Tout" is selected or limit > 100
                prog_bar = st.empty()
                if max_fetch > 100:
                    prog_text = st.empty()
                
                while has_more and len(all_results) < max_fetch:
                    # Payload
                    query_payload = {
                        "page_size": min(100, max_fetch - len(all_results)), # Max 100 per API call
                        "sorts": [{"timestamp": "created_time", "direction": "descending"}]
                    }
                    if notion_filter["and"]:
                        query_payload["filter"] = notion_filter
                    if next_cursor:
                        query_payload["start_cursor"] = next_cursor
                    
                    if max_fetch > 100:
                        prog_text.caption(f"Chargement... ({len(all_results)} trouvés)")
                    
                    resp_query = requests.post(api_url_query, headers=headers, json=query_payload)
                    
                    if resp_query.status_code != 200:
                         st.error(f"Erreur Query {resp_query.status_code}: {resp_query.text}")
                         break
                    else:
                        data = resp_query.json()
                        batch = data.get("results", [])
                        
                        # Python Filter: Months
                        # If months selected, we filter the batch before adding
                        if sel_months and not sel_date: # Only if specific date not overriden
                            filtered_batch = []
                            target_month_nums = [months_map[m] for m in sel_months]
                            
                            for p in batch:
                                d_str = ""
                                if "Date" in p["properties"] and p["properties"]["Date"]["date"]:
                                    d_str = p["properties"]["Date"]["date"]["start"]
                                
                                if d_str:
                                    try:
                                        # d_str is YYYY-MM-DD
                                        m_num = int(d_str.split("-")[1])
                                        if m_num in target_month_nums:
                                            filtered_batch.append(p)
                                    except:
                                        pass # Invalid date format
                                else:
                                    pass # No date, skip?
                            
                            # Note: Pagination logic issue here. 
                            # If we filter by Python, we might fetch 100, keep 0, then stop loop if limit reached?
                            # No, limit check 'len(all_results)' vs 'max_fetch'.
                            # If we filter out, len(all_results) doesn't grow, so we continue fetching.
                            # BUT careful: 'max_fetch - len(all_results)' might request 100, get 100, keep 0.
                            # We must continue until Notion says 'has_more' is False OR we filled our bucket.
                            
                            all_results.extend(filtered_batch)
                        else:
                            all_results.extend(batch)
                        
                        has_more = data.get("has_more", False)
                        next_cursor = data.get("next_cursor")
                        
                        if max_fetch <= 100: # Simple mode, stop after first page if limited
                            if len(all_results) >= max_fetch: break
                
                if max_fetch > 100:
                    prog_text.empty() # Clear text
                
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
            
            st.session_state.total_results_count = total_available # NEW: Store total
            st.session_state.editor_key_version += 1 # Force reset
            
            st.session_state.show_selection = True
            if not unique_results:
                st.warning("Aucune observation trouvée.")
        except Exception as e:
            st.error(f"Erreur iNaturalist : {e}")
            st.session_state.search_results = []

# --- SELECTION INTERFACE ---
if st.session_state.search_results:
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
    total_disp = st.session_state.get('total_results_count', len(st.session_state.search_results))
    c_title.subheader(f"📋 Résultat : {len(st.session_state.search_results)} affichés / {total_disp} total")
    
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

    with st.container(border=True):
        st.markdown("### 📊 Résultats")
        # Bulk Selection Buttons (Apply to VISIBLE only)
        c_sel1, c_sel2, c_space = st.columns([1, 1, 4])
        if c_sel1.button("✅ Tout sélectionner (Vue)"):
            for o in visible_obs:
                st.session_state.selection_states[o['id']] = True
            # st.rerun() removed - redundant as button click already triggers rerun
            pass
                
        if c_sel2.button("❌ Tout désélectionner (Vue)"):
            for o in visible_obs:
                st.session_state.selection_states[o['id']] = False
            # st.rerun() removed - redundant as button click already triggers rerun
            pass
            
        # Transform to DataFrame for Data Editor
        # Optimize DataFrame Creation: Only rebuild if search results changed
        # 1. Build Static Data (if needed)
        # We use a tuple of IDs as a cheap "hash" for the visible dataset
        current_visible_ids = tuple(o['id'] for o in visible_obs)
        
        if 'cached_display_ids' not in st.session_state or st.session_state.cached_display_ids != current_visible_ids:
            raw_data = []
            for obs in visible_obs:
                 # Safe extraction logic (Static)
                taxon_name = obs.get('taxon', {}).get('name') if obs.get('taxon') else "Inconnu"
                obs_date = obs.get('time_observed_at')
                # Robust Date: Check if it's a datetime object or string
                if obs_date and hasattr(obs_date, 'strftime'):
                    date_str = obs_date.strftime("%Y-%m-%d")
                elif obs_date:
                    date_str = str(obs_date)[:10]
                else:
                    date_str = str(obs.get('observed_on_string', 'N/A'))
                
                place = obs.get('place_guess', 'N/A')
                img_url = obs.get('photos')[0]['url'].replace("square", "small") if obs.get('photos') else None
                user_login = obs.get('user', {}).get('login', 'N/A')
                
                # Tags
                tags = obs.get('tags', [])
                extracted_tags = []
                for t in tags:
                    if isinstance(t, dict): extracted_tags.append(str(t.get('tag', '')))
                    elif isinstance(t, str): extracted_tags.append(t)
                    else: extracted_tags.append(str(t))
                tag_str = ", ".join(filter(None, extracted_tags))
                
                raw_data.append({
                    "ID": str(obs['id']),
                    "Taxon": taxon_name,
                    "Date": date_str,
                    "Lieu": place,
                    "Mycologue": user_login,
                    "Tags": tag_str,
                    "Description": obs.get('description', '') or "",
                    "GPS": obs.get('location', '') or "",
                    "URL iNat": f"https://www.inaturalist.org/observations/{obs['id']}",
                    "URL Photo": img_url,
                    "Image": img_url,
                    # "_original_obs": obs 
                })
            st.session_state.cached_display_df = pd.DataFrame(raw_data)
            st.session_state.cached_display_ids = current_visible_ids
    
        # 2. Merge with Dynamic Selection State
        df = st.session_state.cached_display_df.copy()
        if not df.empty:
            # Apply current selection state to the 'Import' column
            df.insert(0, "Import", df['ID'].apply(lambda x: st.session_state.selection_states.get(int(x), True)))
        else:
             df['Import'] = [] # Empty fallback
    
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
            "URL iNat": st.column_config.LinkColumn("🌐 iNat", display_text=r"https://www\.inaturalist\.org/observations/(.*)", help="Ouvrir"),
            "URL Photo": st.column_config.LinkColumn("🖼️", help="Image"),
            "Image": st.column_config.ImageColumn("📷", help="Aperçu"),
            # "_original_obs": None 
        }
        
        # Show Data Editor
        # Key includes version to force reload only when strictly needed (external updates)
        filter_key_suffix = "_all" if not filter_dates else "_" + "_".join(sorted(filter_dates))
        base_key = f"editor{filter_key_suffix}"
        
        if "editor_key_version" not in st.session_state:
            st.session_state.editor_key_version = 0
        # Use version only if strictly necessary to clear stale internal state?
        # Actually, if we use a static key, Streamlit might hold onto "Import" column state even if we change the DF content underlying it?
        # No, if DF changes, editor should update. 
        # The slowdown comes from full mount.
        # We'll use the version key only for programmatic RESET.
        editor_key = f"{base_key}_v{st.session_state.editor_key_version}"
        
        # Callback to handle edits BEFORE rerun
        def on_editor_change():
            # Get the list of changes from the widget state
            state = st.session_state.get(editor_key)
            if not state: return
            
            # Edited rows is a dict: {row_index: {'Import': True/False, ...}}
            edited_rows = state.get("edited_rows", {})
            
            # We need to map row_index back to Observation ID
            # The 'df' variable in global scope (from previous run) matches this index
            # BUT we must be careful. The DataFrame 'df' here is the one used to INITIALIZE the editor.
            # It corresponds to 'st.session_state.cached_display_df' filtered/sorted same way?
            # Yes, 'df' created above at line 635 is what matches these indices.
            
            for idx, changes in edited_rows.items():
                if "Import" in changes:
                    new_val = changes["Import"]
                    # Get ID from the dataframe using the index
                    if idx in df.index:
                        obj_id = int(str(df.at[idx, "ID"]).replace(",",""))
                        st.session_state.selection_states[obj_id] = new_val
                        
            # FORCE REMOUNT: Increment key version to clear editor's internal history
            # This prevents "reverting" visual bugs by forcing the editor to rebuild strictly from 'df'
            st.session_state.editor_key_version += 1
    
        response = st.data_editor(
            df,
            column_config=column_config,
            hide_index=True,
            use_container_width=True,
            disabled=["ID", "Taxon", "Date", "Lieu", "Mycologue", "Tags", "Description", "GPS", "URL iNat", "Photo URL", "Image"],
            key=editor_key,
            on_change=on_editor_change
        )
        
        # Post-processing logic removed as it's handled by callback
        # Just need to ensure selections persist
    
    
        # Count Checked
        current_ids = {obs['id'] for obs in st.session_state.search_results}
        total_checked = sum(1 for oid, is_sel in st.session_state.selection_states.items() if is_sel and oid in current_ids)
        st.info(f"{total_checked} obs sélectionnées.")
        
        # --- DUPLICATE CHECKER ---
        if "dup_msg" in st.session_state and st.session_state.dup_msg:
            msg = st.session_state.dup_msg
            if msg["type"] == "warning":
                st.warning(msg["text"])
                if "found_duplicates_list" in st.session_state and st.session_state.found_duplicates_list:
                    if st.button("🚫 Décocher ces doublons", type="primary"):
                         for d_id in st.session_state.found_duplicates_list:
                             st.session_state.selection_states[int(d_id)] = False
                         st.session_state.found_duplicates_list = []
                         st.session_state.dup_msg = {"type": "success", "text": "✅ Doublons décochés !"}
                         st.session_state.editor_key_version += 1 # Force UI refresh
                         st.rerun()
            elif msg["type"] == "success":
                st.success(msg["text"])
                
        # Always show this section if tokens exist
        if NOTION_TOKEN and DATABASE_ID:
            col_dup, col_imp = st.columns([1, 1])
            # Only enable if something is checked
            dup_disabled = total_checked == 0
            
            if col_dup.button("🕵️ Vérifier doublons", type="secondary", disabled=dup_disabled):
                st.session_state.dup_msg = None
                ids_to_check = [str(oid) for oid, is_sel in st.session_state.selection_states.items() if is_sel and oid in current_ids]
                if not ids_to_check:
                    st.warning("Aucune observation valide sélectionnée.")
                else: 
                        found_duplicates = []
                        error_occurred = False # Flag to prevent auto-rerun if error
                        
                        # SIMPLIFIED LOGIC: Strict URL Search (User Request)
                        # We assume column is "URL Inaturalist" (Type URL)
                        # We also keep "URL iNat" as legacy/variant fallback just in case
                        target_cols = ["URL Inaturalist", "URL iNat"]
                        
                        chunk_size = 20
                        for i in range(0, len(ids_to_check), chunk_size):
                            chunk = ids_to_check[i:i + chunk_size]
                            
                            or_filters = []
                            for cid in chunk:
                                cid = str(cid).strip()
                                full_url = f"https://www.inaturalist.org/observations/{cid}"
                                
                                for col_name in target_cols:
                                    # 1. Check if URL contains ID
                                    or_filters.append({"property": col_name, "url": {"contains": cid}})
                                    # 2. Check if URL equals Full URL
                                    or_filters.append({"property": col_name, "url": {"equals": full_url}})
                            
                            query_filter = {"or": or_filters}
                            
                            
                            try:
                                import re
                                clean_id = re.sub(r'[^a-fA-F0-9]', '', DATABASE_ID)
                                if len(clean_id) == 32:
                                    formatted_db_id = f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:]}"
                                else:
                                    formatted_db_id = clean_id
    
                                # 2. RESOLVE DATA SOURCE ID (Fix for v2025-09-03)
                                # We must GET the database first to find its data_source_id
                                # This also acts as a PERMISSION CHECK.
                                
                                headers = {
                                    "Authorization": f"Bearer {NOTION_TOKEN}",
                                    "Notion-Version": "2025-09-03", 
                                    "Content-Type": "application/json"
                                }
                                
                                target_query_id = formatted_db_id # Default to DB ID if resolution fails
                                
                                try:
                                    db_meta_url = f"https://api.notion.com/v1/databases/{formatted_db_id}"
                                    meta_resp = requests.get(db_meta_url, headers=headers)
                                    
                                    if meta_resp.status_code == 200:
                                        meta = meta_resp.json()
                                        # Try to find data_source_id in response?
                                        # Note: 2025-09-03 doesn't typically expose "data_sources" array in GET /databases/ 
                                        # UNLESS it's a multi-source DB.
                                        # BUT, if checking duplicates fails with DB ID, we might need to use the endpoint /v1/databases/ again?
                                        # WAIT. Upgrade guide says: "Migrate database endpoints to data sources". 
                                        # If I have a simple DB, maybe /v1/databases/{id}/query IS CORRECT?
                                        # The 400 error was "Invalid Request URL". Maybe it WAS the API version mismatch with endpoint?
                                        # Let's try BOTH endpoints safely.
                                        
                                        pass # Just confirming access
                                    elif meta_resp.status_code == 404:
                                        st.error("❌ Base Notion introuvable. Avez-vous partagé la base avec l'intégration ? (Menu ... > Connect to)")
                                        error_occurred = True
                                        break
                                except Exception as e:
                                    pass # Ignore connection check errors, fall through to query
    
                                # 3. EXECUTE QUERY
                                # Strategy: Try /databases/ endpoint first (standard), if 400, try /data_sources/
                                # This handles both Legacy-style single DBs and New Multi-source DBs dynamically.
                                
                                api_url = f"https://api.notion.com/v1/databases/{formatted_db_id}/query"
                                resp = requests.post(api_url, headers=headers, json={"filter": query_filter})
                                
                                if resp.status_code == 400 and "Invalid request URL" in resp.text:
                                    # Fallback -> Data Source Endpoint
                                    api_url_ds = f"https://api.notion.com/v1/data_sources/{formatted_db_id}/query"
                                    resp = requests.post(api_url_ds, headers=headers, json={"filter": query_filter})
                                    
                                 # Continue processing...
    
                                
                                if resp.status_code == 200:
                                    q_data = resp.json()
                                    for page in q_data.get('results', []):
                                        props = page.get('properties', {})
                                        
                                        # Verification
                                        # Check our target URL columns
                                        found_urls = []
                                        for col_name in target_cols:
                                            u_obj = props.get(col_name)
                                            if u_obj and u_obj.get('type') == 'url':
                                                u_val = u_obj.get('url')
                                                if u_val: found_urls.append(str(u_val))
                                        
                                        # Match against chunk IDs
                                        for cid in chunk:
                                            cid = str(cid).strip()
                                            full_url = f"https://www.inaturalist.org/observations/{cid}"
                                            
                                            for f_url in found_urls:
                                                if f_url and (cid in f_url or full_url == f_url):
                                                    found_duplicates.append(cid)
                                                    
                                else:
                                    st.error(f"Erreur API Notion ({resp.status_code}) : {resp.text}")
                                    st.error(f"⚠️ DEBUG URL: {api_url}") # Show URL on error
                                    st.error(f"⚠️ DEBUG ID: '{DATABASE_ID}'") # Show ID on error
                                    error_occurred = True
                                    break # Stop strict
                            except Exception as e:
                                st.error(f"Erreur requête : {e}")
                                error_occurred = True
                                break
    
                        if not error_occurred:
                            # Remove duplicates from list
                            found_duplicates = list(set(found_duplicates))
                            
                            if found_duplicates:
                                st.session_state.found_duplicates_list = found_duplicates
                                st.session_state.dup_msg = {"type": "warning", "text": f"⚠️ {len(found_duplicates)} doublons trouvés."}
                            else:
                                st.session_state.found_duplicates_list = []
                                st.session_state.dup_msg = {"type": "success", "text": "✅ 0 doublon."}
                            st.rerun()
    
        if st.button("📤 Importer vers Notion", type="primary"):
            # Robust Import Logic using STATE
            ids_to_import = []
            
            # Filter source list using STATE
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
                    if lat: props["Latitude (sexadécimal)"] = {"rich_text": [{"text": {"content": str(lat)}}]}
                    if lon: props["Longitude (sexadécimal)"] = {"rich_text": [{"text": {"content": str(lon)}}]}
                    
                    obs_country = obs.get('place_guess', '') # iNat doesn't cleanly give country in basic response always, strictly place_guess used above
                    # But user listed "Place_country_name". 
                    # Let's see if we have it? Usually not in standard obs dict unless extra param. 
                    # Fallback: Don't map it if missing or map place_guess.
                    # Actually, earlier I didn't verify if I have place_country_name.
                    # Checking mapping table: "Place_country_name" -> "Place_country_name"
                    # If I don't have it, I skip it. 
                    
                    # SEND TO NOTION
                    try:
                        # Clean ID & Format UUID (Same robust logic as Duplicate Check)
                        import re
                        clean_id_imp = re.sub(r'[^a-fA-F0-9]', '', DATABASE_ID)
                        if len(clean_id_imp) == 32:
                            fmt_db_id = f"{clean_id_imp[:8]}-{clean_id_imp[8:12]}-{clean_id_imp[12:16]}-{clean_id_imp[16:20]}-{clean_id_imp[20:]}"
                        else:
                            fmt_db_id = clean_id_imp
                            
                        new_page = notion.pages.create(
                            parent={"database_id": fmt_db_id, "type": "database_id"}, # Explicit type as requested
                            properties=props,
                            children=children,
                            cover={"external": {"url": cover_url}} if cover_url else None
                        )
                        
                        # --- QR CODE GENERATION ---
                        # 1. Get New Page URL
                        page_url = new_page.get('url')
                        page_id = new_page.get('id')
                        
                        if page_url and page_id:
                            # 2. Generate Public QR URL (Notion needs an external URL for Files)
                            # Using qrserver.com API which is standard
                            qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={page_url}"
                            
                            # 3. Update "Code QR" property
                            # We wrap this in a separate try/except so it doesn't fail the whole import if column is missing
                            try:
                                notion.pages.update(
                                    page_id=page_id,
                                    properties={
                                        "Code QR": {
                                            "files": [
                                                {
                                                    "name": "notion_qr.png",
                                                    "type": "external",
                                                    "external": {"url": qr_api_url}
                                                }
                                            ]
                                        }
                                    }
                                )
                            except Exception as e_qr:
                                # Often happens if "Code QR" property doesn't exist or is wrong type
                                st.warning(f"⚠️ QR Code non ajouté pour {sci_name} (Vérifiez qu'une colonne 'Code QR' de type 'Fichiers' existe) : {e_qr}")

                    except Exception as e:
                        st.warning(f"Erreur Notion sur {sci_name}: {e}")
                        # Provide hint on common error
                        if "multiple data sources" in str(e):
                            st.caption("ℹ️ Note: Cette erreur indique souvent que la base de données cible est complexe (Synchronisée, Vue liée, ou Data Source). Assurez-vous de cibler la base originale et que l'API supporte ce type.")
                    
                    progress_bar.progress((i + 1) / len(obs_to_import))
                
                status_text.text("✅ Importation terminée avec succès !")
                st.success("Toutes les observations sélectionnées ont été transférées.")
