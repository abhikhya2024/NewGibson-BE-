import requests
import urllib.parse
from myapp.models import TranscriptEntry  # Update with your actual app name
import chardet
from .openai import GibsonMetadataInference
import re
import json
import os
# Configuration (move to settings or .env for production)
from dotenv import load_dotenv
load_dotenv()
# Configuration (move to settings or .env for production)
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
SHAREPOINT_HOST = "cloudcourtinc.sharepoint.com"
SITE_PATH = "/sites/docsshblageunesse"
FOLDER = "FormattedQA"
TEXTFILESFOLDER = "OriginalFiles"

def get_access_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default"
    }
    res = requests.post(url, data=data)
    res.raise_for_status()
    return res.json()["access_token"]

def fetch_json_files_from_sharepoint():
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Get site ID
    site_res = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_HOST}:{SITE_PATH}",
        headers=headers
    )
    site_res.raise_for_status()
    site_id = site_res.json()["id"]

    # Step 2: Get drive ID
    drive_res = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
        headers=headers
    )
    drive_res.raise_for_status()
    drive = next((d for d in drive_res.json()["value"] if d["name"] == "Documents"), None)
    if not drive:
        raise Exception("Documents drive not found")

    drive_id = drive["id"]

    # Step 3: List all JSON files in the folder

    files_res = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FOLDER}:/children",
        headers=headers
    )
    files_res.raise_for_status()
    files = files_res.json().get("value", [])

    total_records = 0
    saved_files = []

    for file in files:
        filename = file.get("name")
        if not filename.endswith(".json"):
            continue

        file_path = f"{FOLDER}/{filename}"
        encoded_file_path = urllib.parse.quote(file_path)
        file_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{encoded_file_path}:/content"

        file_res = requests.get(file_url, headers=headers)
        file_res.raise_for_status()

        try:
            data = file_res.json()
            entries = [
                TranscriptEntry(
                    question=record.get("question"),
                    answer=record.get("answer"),
                    cite=record.get("cite"),  # Make sure your JSON uses this key
                    filename=filename
                )
                for record in data
            ]
            TranscriptEntry.objects.bulk_create(entries, batch_size=100)
            total_records += len(entries)
            saved_files.append(filename)

        except Exception as e:
            print(f"Error parsing {filename}: {e}")

    return {
        "status": "success",
        "files_processed": saved_files,
        "records_inserted": total_records
    }

# def fetch_text_files_from_sharepoint():
#     token = get_access_token()
#     headers = {"Authorization": f"Bearer {token}"}

#     # Step 1: Get site ID
#     site_res = requests.get(
#         f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_HOST}:{SITE_PATH}",
#         headers=headers
#     )
#     site_res.raise_for_status()
#     site_id = site_res.json()["id"]

#     # Step 2: Get drive ID
#     drive_res = requests.get(
#         f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
#         headers=headers
#     )
#     drive_res.raise_for_status()
#     drive = next((d for d in drive_res.json()["value"] if d["name"] == "Documents"), None)
#     if not drive:
#         raise Exception("Documents drive not found")
#     drive_id = drive["id"]

#     # Step 3: List items in the folder
#     files_res = requests.get(
#         f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{TEXTFILESFOLDER}:/children",
#         headers=headers
#     )
#     files_res.raise_for_status()
#     files = files_res.json().get("value", [])

#     saved_files = []
#     total_records = 0

#     for file in files:
#         # filename = file.get("name")
#         # is_file = "file" in file  # filter out folders

#         # if is_file and filename.lower().endswith(".txt"):
#         #     print(f"✔️ Found .txt file: {filename}")
#         #     saved_files.append({
#         #         "filename": filename,
#         #         "id": file["id"],
#         #         "downloadUrl": file["@microsoft.graph.downloadUrl"]  # optional
#         #     })
#         #     total_records += 1
#         # else:
#         #     print(f"✖️ Skipped: {filename}")
        
    

#     print(f"\n✅ Total TXT files fetched: {total_records}")
#     return saved_files

def format_name(name):
    pattern = r'^(Mr\.|Ms\.|Mrs\.|Dr\.|Hon\.|Prof\.)\s+'
    cleaned = re.sub(pattern, '', name or '', flags=re.IGNORECASE).strip()
    if not cleaned:
        return ""
    parts = cleaned.split()
    if len(parts) >= 2:
        first_name = ' '.join(parts[:-1]).title()
        last_name = parts[-1].title()
        return f"{last_name}, {first_name}"
    return cleaned.title()
def fetch_text_files_from_sharepoint():
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Get site ID
    site_res = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_HOST}:{SITE_PATH}",
        headers=headers
    )
    site_res.raise_for_status()
    site_id = site_res.json()["id"]

    # Step 2: Get drive ID
    drive_res = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
        headers=headers
    )
    drive_res.raise_for_status()
    drive = next((d for d in drive_res.json()["value"] if d["name"] == "Documents"), None)
    if not drive:
        raise Exception("Documents drive not found")

    drive_id = drive["id"]

    # Step 3: List items in the folder
    files_res = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{TEXTFILESFOLDER}:/children",
        headers=headers
    )
    files_res.raise_for_status()
    files = files_res.json().get("value", [])

    total_records = 0
    metadata = []
    witness_names = []
    for file in files:
        filename = file.get("name")
        is_file = "file" in file

        if is_file and filename.lower().endswith(".txt"):
            print(f"📄 Found .txt file: {filename}")
            download_url = file.get("@microsoft.graph.downloadUrl")
            if not download_url:
                print(f"⚠️ No download URL for: {filename}")
                continue

            # Step 4: Download and decode file content in memory
            download_res = requests.get(download_url)
            print(download_res)
            if download_res.status_code != 200:
                print(f"❌ Failed to download {filename}")
                continue

            raw_data = download_res.content
            encoding_info = chardet.detect(raw_data)
            file_encoding = encoding_info['encoding'] or 'utf-8'

            try:
                input_text = raw_data.decode(file_encoding)
            except Exception as e:
                print(f"⚠️ Could not decode {filename}: {e}")
                continue

            # Optional: truncate for processing
            truncated_input_text = " ".join(input_text.split()[:5000])
            try:
                raw_response = GibsonMetadataInference(input_text=truncated_input_text).generate_structure()

                if isinstance(raw_response, str):
                    cleaned = re.sub(r"^```json|```$", "", raw_response.strip(), flags=re.IGNORECASE).strip()
                    extracted_data = json.loads(cleaned)
                else:
                    extracted_data = raw_response

                # Format names
                raw_witness_name = extracted_data.get("witness_name", "").strip()
                print("raw_witness_name", raw_witness_name)
                witness_type = extracted_data.get("witness_type", "").strip()
                print("witness_type", witness_type)

                extracted_data["witness_name"] = format_name(raw_witness_name)
                witness_names.append(raw_witness_name)

            except Exception as e:
                print(f"⛔ Skipping file {filename} due to error: {e}")
                continue

    print(f"\n✅ Total .txt files processed: {total_records}")
    return metadata, witness_names