import streamlit as st
from notion_client import Client
import json
import os

# Mock secrets if running directly
if not os.path.exists(".streamlit/secrets.toml"):
    # Try to grab from env or hard fail specific to user
    pass

try:
    print("--- DEBUGGING NOTION CLIENT ---")
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
    DATABASE_ID = st.secrets["DATABASE_ID"]
    
    if DATABASE_ID and "notion.so" in DATABASE_ID:
        path_part = DATABASE_ID.split("?")[0]
        DATABASE_ID = path_part.split("/")[-1]
        
    client = Client(auth=NOTION_TOKEN)
    print(f"Client: {client}")
    print(f"Databases Endpoint: {client.databases}")
    print(f"Methods of databases: {dir(client.databases)}")
    
    print("\n--- FETCHING SCHEMA ---")
    db = client.databases.retrieve(DATABASE_ID)
    props = db.get("properties", {})
    
    if "Mycologue" in props:
        print(f"Property 'Mycologue': {json.dumps(props['Mycologue'], indent=2)}")
    else:
        print("Property 'Mycologue' NOT FOUND")
        print("Available Properties:", list(props.keys()))

    if "Projet d'inventaire" in props:
         print(f"Property 'Projet': {json.dumps(props['Projet d\'inventaire'], indent=2)}")
    
except Exception as e:
    print(f"CRITICAL ERROR: {e}")
