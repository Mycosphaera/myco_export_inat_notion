# Portail Myco (iNat Sync & Fongarium)

**Myco Export iNat Notion** est une application web Streamlit conçue pour les mycologues de MycoQuébec/Mycosphaera. Elle facilite la synchronisation des observations entre iNaturalist et Notion, la gestion des numéros de fongarium, et la génération d'étiquettes PDF pour les spécimens.

## 🚀 Fonctionnalités

* **Authentification Sécurisée** : Système de connexion et d'inscription (basé sur une liste blanche et validation par email).
* **Synchronisation iNaturalist** : Recherche et import d'observations depuis iNaturalist.
* **Intégration Notion** : Connexion directe à une base de données Notion pour récupérer les listes de mycologues et de projets.
* **Gestion de Profil** :
  * Liaison des comptes Notion et iNaturalist.
  * Gestion des préfixes de fongarium (ex: MRD0001).
  * Statistiques personnelles (Nombre d'observations, dernier numéro de collection).
* **Génération d'Étiquettes** : Création de planches d'étiquettes PDF avec QR codes pour les spécimens, incluant les coordonnées GPS.
* **Tableau de Bord** : Vue d'ensemble des statistiques et outils rapides.

## 🛠️ Prérequis

* Python 3.9+
* Un compte Notion avec une intégration API configurée.
* Une base de données Supabase (pour la gestion des utilisateurs).

## 📦 Installation

1. Clonez ce dépôt :

    ```bash
    git clone <votre-repo-url>
    cd myco_export_inat_notion
    ```

2. Installez les dépendances :

    ```bash
    pip install -r requirements.txt
    ```

## ⚙️ Configuration

L'application utilise les secrets Streamlit pour la configuration sensible. Créez un fichier `.streamlit/secrets.toml` à la racine du projet :

```toml
[notion]
token = "secret_votre_token_notion"
database_id = "votre_database_id_notion"

[supabase]
url = "votre_url_supabase"
key = "votre_cle_anon_supabase"

# Optionnel : Liste blanche d'emails admin ou spécifiques si non géré par whitelist.py
```

*Note : Le fichier `whitelist.py` contient également la liste des emails autorisés à s'inscrire.*

## ▶️ Utilisation

Lancez l'application avec Streamlit :

```bash
streamlit run app.py
```

L'application sera accessible via votre navigateur (par défaut sur `http://localhost:8501`).

## 📂 Structure du Projet

* `app.py` : Point d'entrée principal de l'application Streamlit. Contient la logique d'interface, d'authentification et de navigation.
* `database.py` : Gestion des connexions et requêtes vers Supabase (profils utilisateurs).
* `labels.py` : Module de génération des étiquettes PDF (ReportLab).
* `whitelist.py` : Liste des utilisateurs autorisés (permet de restreindre l'inscription).
* `check_user_status.py`, `inspect_schema.py` : Scripts utilitaires pour le débogage et la maintenance.

## 🤝 Contribution

Les contributions sont les bienvenues. Veuillez vous assurer de tester vos changements localement avant de soumettre une Pull Request.

---
*Développé pour Mycosphaera / MycoQuébec.*
