import requests
import urllib.parse
from myapp.models import TranscriptEntry  # Update with your actual app name
import chardet
from .openai import GibsonMetadataInference
import re
import json
import os
from dotenv import load_dotenv
from project.models import Transcript
import spacy
nlp = spacy.load("en_core_web_sm")

load_dotenv()
# Configuration (move to settings or .env for production)
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
SHAREPOINT_HOST = os.getenv("SHAREPOINT_HOST")
SITE_PATH1 = "/sites/DocsGibsonDemo"
FOLDER = "FormattedQA"
TEXTFILESFOLDER = "OriginalFiles"
SITE_PATH2 = "/sites/DocsFarrarBallTireMFG"
FILEMETADATAPATH = "Extras"
SITE_PATH3 = "/sites/DocsSHB-PM-Proctor"
JSON_FILENAME = "file_metadata_master.json"
TAXONOMY_FILENAME = "witness_taxonomy.json"
SITE_PATH4 = "/sites/DocsSHBPMCummings"
DB_NAMES = ['default', 'cummings', 'prochaska', 'proctor', 'ruckd']  # 5 databases


import logging
logger = logging.getLogger("logging_handler")  # same as views.py
logger.info("✅ Log from sharepoint_utils.py")

def extract_state(text: str) -> str | None:
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ == "GPE":  # Geo-Political Entity
            return ent.text
    return None

def get_access_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default"
    }

    logger.info("Data!!!!!!", data)
    res = requests.post(url, data=data)
    res.raise_for_status()
    return res.json()["access_token"]

def get_dive_id(site):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Get site ID
    site_res = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_HOST}:{SITE_PATH1}",
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
    return drive_id

def get_dive_id(site):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Get site ID
    site_res = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_HOST}:{site}",
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
    return drive_id


def convert_json_filename_to_txt(json_filename):
    # Remove the _formatted.json suffix
    if json_filename.endswith("_formatted.json"):
        base_name = json_filename.replace("_formatted.json", "")
    else:
        base_name = json_filename.replace(".json", "")
    
    # Add .txt extension
    txt_filename = f"{base_name}.txt"
    return txt_filename

def fetch_json_files_from_sharepoint():
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    results = []

    try:
        logger.info("Fetching drive id…")
        drive_id = get_dive_id("/sites/DocsGibsonDemo")

        files_res = requests.get(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FOLDER}:/children",
            headers=headers
        )
        files_res.raise_for_status()
        files = files_res.json().get("value", [])
    except Exception as e:
        logger.error(f"⛔ error: {e}")
        return []

    for file in files:
        filename = file.get("name")
        if not filename.endswith(".json"):
            continue

        txt_file_name = convert_json_filename_to_txt(filename)

        # ✅ check in *all databases* for transcript
        transcript_exists = any(
            Transcript.objects.using(db).filter(name=txt_file_name).exists()
            for db in DB_NAMES
        )
        if not transcript_exists:
            logger.warning(f"❌ Skipping: No transcript found for {txt_file_name}")
            continue

        # Fetch file content
        file_path = f"{FOLDER}/{filename}"
        encoded_file_path = urllib.parse.quote(file_path)
        file_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{encoded_file_path}:/content"

        try:
            file_res = requests.get(file_url, headers=headers)
            file_res.raise_for_status()
            data = file_res.json()

            for record in data:
                results.append({
                    "question": record.get("question"),
                    "answer": record.get("answer"),
                    "cite": record.get("cite"),
                    "index": record.get("index"),
                    "filename": txt_file_name
                })
        except Exception as e:
            logger.error(f"⛔ Skipping file {filename} due to error: {e}")
            continue

    print(f"\n✅ Total QA Pairs processed: {len(results)}")
    return results

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

def fetch_witness_from_sharepoint():
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    drive_id = get_dive_id("/site/DocsGibsonDemo")

    files_res = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FILEMETADATAPATH}:/children",
        headers=headers
    )

    files_res.raise_for_status()
    files = files_res.json().get("value", [])

    results = []  # ✅ Your final output list


def fetch_jurisdictions():
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    drive_id = get_dive_id("/sites/DocsGibsonDemo")

    # Download the JSON file content
    file_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FILEMETADATAPATH}/{JSON_FILENAME}:/content"
    response = requests.get(file_url, headers=headers)
    response.raise_for_status()

    data = response.json()
    results = []

    for entry in data:
        jurisdiction = entry.get("jurisdiction")
        if jurisdiction:
            
            results.append({
                "jurisdiction": extract_state(jurisdiction),
            })
    return results

def fetch_attorney():
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    drive_id = get_dive_id("/sites/DocsGibsonDemo")

    # Download the JSON file content
    file_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FILEMETADATAPATH}/{JSON_FILENAME}:/content"
    response = requests.get(file_url, headers=headers)
    response.raise_for_status()

    data = response.json()   # <-- this is a list of dicts
    results = []

    for entry in data:
        attorneys = {
            "taking": entry.get("taking_attorney"),
            "defending": entry.get("defending_attorney"),
        }

        for atty_type, atty_info in attorneys.items():
            if atty_info and (atty_info.get("name") or atty_info.get("law_firm")):
                results.append({
                    "type": atty_type,
                    "name": atty_info.get("name"),
                    "law_firm": atty_info.get("law_firm"),
                    "transcript_name": entry.get("transcript_name"),  # optional context
                })

    return results



def fetch_witness_names_and_transcripts():
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    drive_id = get_dive_id("/sites/DocsGibsonDemo")

    # Download the JSON file content
    file_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FILEMETADATAPATH}/{JSON_FILENAME}:/content"
    response = requests.get(file_url, headers=headers)
    response.raise_for_status()

    data = response.json()

    # Extract witness name + transcript name pairs
    results = []
    for entry in data:
        witness_name = entry.get("witness_name")
        print(witness_name)
        transcript_name = entry.get("transcript_name")+".txt"
        transcript_date = entry.get("transcript_date")
        case_name = entry.get("case_name")
        if witness_name and transcript_name:
            results.append({
                "witness_name": witness_name,
                "transcript_name": transcript_name,
                "transcript_date": transcript_date,
                "case_name": case_name
            })

    return results

def fetch_from_sharepoint():
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    drive_id = get_dive_id(SITE_PATH1)

    files_res = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{TEXTFILESFOLDER}:/children",
        headers=headers
    )
    files_res.raise_for_status()
    files = files_res.json().get("value", [])

    results = []  # ✅ Your final output list

    for file in files:
        filename = file.get("name")
        print("filename", filename)
        is_file = "file" in file

        if is_file and filename.lower().endswith(".txt"):
            print(f"📄 Found .txt file: {filename}")
            download_url = file.get("@microsoft.graph.downloadUrl") # direct file download link
            if not download_url:
                print(f"⚠️ No download URL for: {filename}")
                continue
            web_url = file.get("webUrl")  # SharePoint UI link to view in browser

            download_res = requests.get(download_url)
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

            truncated_input_text = " ".join(input_text.split()[:5000])

            try:
                raw_response = GibsonMetadataInference(input_text=truncated_input_text).generate_structure()

                if isinstance(raw_response, str):
                    cleaned = re.sub(r"^```json|```$", "", raw_response.strip(), flags=re.IGNORECASE).strip()
                    extracted_data = json.loads(cleaned)
                else:
                    extracted_data = raw_response

                raw_witness_name = extracted_data.get("witness_name", "").strip()
                transcript_date = extracted_data.get("transcript_date", "").strip()
                case_name = extracted_data.get("case_name", "").strip()
                print("test", raw_witness_name, case_name)
                # formatted_name = format_name(raw_witness_name)
                # parts = formatted_name.strip().split()
                # if not parts:
                #     return "", ""  # empty string case
                # first_name = parts[0]
                # last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

                if not raw_witness_name:
                    continue

                # ✅ Append to results
                results.append({
                    "transcript_name": filename,
                    "witness_name": raw_witness_name,
                    "transcript_date": transcript_date,
                    "sharepoint_url": web_url,  # ✅ Add the SharePoint UI link
                    "case_name": case_name


                })

            except Exception as e:
                print(f"⛔ Skipping file {filename} due to error: {e}")
                continue

    print(f"\n✅ Total .txt files processed: {len(results)}")
    return results

def fetch_taxonomy_from_sharepoint():
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    drive_id = get_dive_id("/sites/DocsGibsonDemo")

    # Download the JSON file content
    file_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FILEMETADATAPATH}/{TAXONOMY_FILENAME}:/content"
    response = requests.get(file_url, headers=headers)
    response.raise_for_status()

    data = response.json()

    # Extract witness alignments & types
    results = []
    alignments = set()
    witness_types = set()

    witnesses = data.get("Witness", [])
    for entry in witnesses:
        witness_name = entry.get("Name")
        alignment = entry.get("Alignment")
        types = entry.get("Types", [])

        if alignment:
            alignments.add(alignment)

        for t in types:
            transcript_name = t.get("TranscriptName")
            witness_type = t.get("Type")
            expert_type = t.get("ExpertType")
            if witness_type:
                witness_types.add(witness_type)
            print("align", alignment)
            results.append({
                "witness_name": witness_name,
                "alignment": alignment,
                "transcript_name": transcript_name+".txt",
                "witness_type": witness_type,
                "expert_type": expert_type
            })

    # Return both
    return results