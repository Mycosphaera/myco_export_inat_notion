import streamlit as st
from notion_client import Client
import json

try:
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
    DATABASE_ID = st.secrets["DATABASE_ID"]
    
    # Sanitize ID again as in app.py
    if DATABASE_ID and "notion.so" in DATABASE_ID:
        path_part = DATABASE_ID.split("?")[0]
        DATABASE_ID = path_part.split("/")[-1]
    
    notion = Client(auth=NOTION_TOKEN)
    
    db_info = notion.databases.retrieve(database_id=DATABASE_ID)
    
    print("DB Title:", db_info['title'][0]['plain_text'] if db_info['title'] else "No Title")
    print("Properties:")
    for name, prop in db_info['properties'].items():
        print(f"- {name} ({prop['type']})")
        if prop['type'] == 'select':
            options = [opt['name'] for opt in prop['select']['options']]
            print(f"  Options: {options}")

except Exception as e:
    print(f"Error: {e}")
