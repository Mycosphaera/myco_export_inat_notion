
import tomllib
from supabase import create_client
import sys

# Log output
sys.stdout = open("user_status_log.txt", "w", encoding="utf-8")

try:
    with open(".streamlit/secrets.toml", "rb") as f:
        secrets = tomllib.load(f)

    def get_val(section, keys):
        for k in keys: 
            if k in secrets[section]: return secrets[section][k]
        return None

    url = get_val("supabase", ["url", "URL", "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"])
    key = get_val("supabase", ["key", "KEY", "SUPABASE_KEY", "SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY"])

    supabase = create_client(url, key)
    
    target_email = "info@mycosphaera.com"
    print(f"Checking status for: {target_email}")
    
    # 1. Check existence
    res = supabase.table("user_profiles").select("*").eq("auth_username", target_email).execute()
    
    if res.data:
        print("✅ USER FOUND in DB:")
        print(res.data)
    else:
        print("❌ USER NOT FOUND in DB.")
        
    # 2. Simulate Login Logic exactly as in database.py
    print("\nSimulating 'get_user_by_email'...")
    try:
        res_login = supabase.table("user_profiles").select("*").eq("auth_username", target_email).execute()
        if res_login.data:
             print("✅ Login Simulation: SUCCESS. User data retrieved.")
             print(res_login.data[0])
        else:
             print("❌ Login Simulation: FAILED. returned empty data.")
    except Exception as e:
        print(f"❌ Login Simulation: EXCEPTION: {e}")


except Exception as e:
    print(f"Script Error: {e}")
