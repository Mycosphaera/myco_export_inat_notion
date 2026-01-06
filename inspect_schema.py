import streamlit as st
import tomllib
from supabase import create_client, Client

# --- SETUP SECRETS ---
try:
    with open(".streamlit/secrets.toml", "rb") as f:
        secrets = tomllib.load(f)
except FileNotFoundError:
    print("❌ secrets.toml not found.")
    exit()

def get_secret(keys, section="supabase"):
    # Try section
    if section in secrets:
        for k in keys:
            if k in secrets[section]: return secrets[section][k]
    # Try root
    for k in keys:
        if k in secrets: return secrets[k]
    return None

url = get_secret(["url", "URL", "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"])
key = get_secret(["key", "KEY", "SUPABASE_KEY", "SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY"])

if not url or not key:
    print("❌ Supabase keys missing.")
    exit()

supabase: Client = create_client(url, key)

print("✅ Client initialized.")

# --- INSPECT SCHEMA ---
try:
    # We can't query schema directly with simple client easily, but we can fetch one row and see keys
    print("Fetching one row from user_profiles...")
    response = supabase.table("user_profiles").select("*").limit(1).execute()
    
    if response.data:
        print("Columns found:")
        for k in response.data[0].keys():
            print(f" - {k}")
    else:
        print("User profiles table empty or not readable. Trying default insert to see errors if missing cols?")

except Exception as e:
    print(f"Error fetching schema: {e}")
