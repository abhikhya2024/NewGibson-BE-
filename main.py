import requests
import urllib.parse
import os
# ---------------------------
# 🔐 Azure AD Credentials
# ---------------------------
from dotenv import load_dotenv
load_dotenv()
# Configuration (move to settings or .env for production)
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

# ---------------------------
# 📁 SharePoint Info
# ---------------------------
SHAREPOINT_HOST = "cloudcourtinc.sharepoint.com"
SITE_PATH = "/sites/Docs3MBairHugger"
FOLDER = "FormattedQA"
FILENAME = "2014.09.11 - Walton, Wilma - Dep Transcript (ASCII)_formatted"

# ---------------------------
# ✅ Get Microsoft Graph Token
# ---------------------------
def get_access_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default"
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]

# ---------------------------
# 📄 Download JSON File
# ---------------------------
def fetch_sharepoint_file():
    try:
        token = get_access_token()
        headers = {
            "Authorization": f"Bearer {token}"
        }

        # Step 1: Get site ID
        site_url = f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_HOST}:{SITE_PATH}"
        site_res = requests.get(site_url, headers=headers)
        site_res.raise_for_status()
        site_id = site_res.json()["id"]

        # Step 2: Get drives
        drives_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives"
        drives_res = requests.get(drives_url, headers=headers)
        drives_res.raise_for_status()
        drives = drives_res.json()["value"]

        # Find 'Documents' drive
        documents_drive = next((d for d in drives if d["name"] == "Documents"), None)
        if not documents_drive:
            raise Exception("Documents drive not found.")
        drive_id = documents_drive["id"]

        # Step 3: Download file content
        encoded_filename = urllib.parse.quote(f"{FILENAME}.json")
        file_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FOLDER}/{encoded_filename}:/content"
        file_res = requests.get(file_url, headers=headers)
        file_res.raise_for_status()

        # If the content is JSON, parse and return
        try:
            json_data = file_res.json()
            print("✅ Fetched JSON Content:")
            print(json_data)
        except ValueError:
            print("⚠️ File is not valid JSON or could not be decoded.")

    except Exception as e:
        print("❌ Error:", e)

# ---------------------------
# Run the script
# ---------------------------
if __name__ == "__main__":
    fetch_sharepoint_file()
