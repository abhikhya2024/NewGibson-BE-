import requests
import urllib.parse
from myapp.models import TranscriptEntry  # Update with your actual app name
import chardet
from .openai import GibsonMetadataInference
import re
import json
import os, traceback
from dotenv import load_dotenv
from project.models import Transcript
import spacy
nlp = spacy.load("en_core_web_sm")
import msal
from whoosh.index import create_in
from whoosh.fields import Schema, TEXT, ID
from whoosh import index
from whoosh.analysis import RegexTokenizer, LowercaseFilter
from whoosh.qparser import MultifieldParser, OrGroup, AndGroup
from whoosh.query import FuzzyTerm, Or as OrQuery, And as AndQuery, Prefix
from rapidfuzz import fuzz
import shutil
import time
from whoosh.index import LockError
import fcntl
from whoosh.fields import Schema, TEXT, ID
from whoosh.query import Or, And, Term
from whoosh.qparser import QueryParser
from whoosh.query import FuzzyTerm, Or, And, Prefix
import re
import fcntl, time, os
from whoosh import index
from whoosh.query import Every

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
DB_NAMES = ['default']  # 5 databases
AUTHORITY = f"https://login.microsoftonline.com/TENANT_ID"
SCOPE = ["https://graph.microsoft.com/.default"]
AUTHORITY2 = f"https://login.microsoftonline.com/{TENANT_ID}"

import logging
logger = logging.getLogger("logging_handler")  # same as views.py
logger.info("✅ Log from sharepoint_utils.py")

def extract_state(text: str) -> str | None:
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ == "GPE":  # Geo-Political Entity
            return ent.text
    return None

def get_token():
    """Get Microsoft Graph access token using client credentials"""
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY2,
        client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_silent(SCOPE, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=SCOPE)

    if "access_token" not in result:
        raise Exception("Could not obtain token", result.get("error_description"))

    return result["access_token"]
def get_access_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    logger.info("url!!!!!!", url)

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
    
    try:
        # Download the JSON file content
        file_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FILEMETADATAPATH}/{JSON_FILENAME}:/content"
        response = requests.get(file_url, headers=headers)
        response.raise_for_status()

        data = response.json()
        # Extract witness name + transcript name pairs
        results = []
        for entry in data:
            witness_name = entry.get("witness_name")
            logger.info(witness_name, "witness")
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
        print("results***********************************************", results)
        return results
    
    except Exception as e:
        print("exception", e)

        
    

    

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

def download_all_transcripts():
    """Download all .txt transcripts from SharePoint TextFiles folder to user's Downloads."""
    logger.info("Starting download of all transcripts")

    # --- Authenticate with MSAL ---
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_silent(SCOPE, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=SCOPE)

    if "access_token" not in result:
        raise Exception("❌ Could not obtain token", result.get("error_description"))

    access_token = result["access_token"]
    logger.info("Fetched token")

    # --- Settings ---
    drive_name = "Documents"
    folder = "TextFiles"

    # Step 1: Get Site ID
    site_res = requests.get(
        "https://graph.microsoft.com/v1.0/sites/cloudcourtinc.sharepoint.com:/sites/DocsGibsonDemo:/?select=id,webUrl",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    site_res.raise_for_status()
    site_id = site_res.json()["id"]

    # Step 2: Get Drive ID
    drive_res = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    drive_res.raise_for_status()
    drive = next(d for d in drive_res.json()["value"] if d["name"] == drive_name)
    drive_id = drive["id"]

    # Step 3: List all items in TextFiles folder
    list_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder}:/children"
    list_res = requests.get(list_url, headers={"Authorization": f"Bearer {access_token}"})
    list_res.raise_for_status()
    items = list_res.json().get("value", [])

    # Step 4: Download only .txt files
    downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(downloads_path, exist_ok=True)
    logger.info("testing 1111")

    downloaded_files = []

    for item in items:
        name = item["name"]
        if name.lower().endswith(".txt"):
            download_url = item["@microsoft.graph.downloadUrl"]
            file_res = requests.get(download_url)
            if file_res.status_code == 200:
                file_path = os.path.join(downloads_path, name)
                with open(file_path, "wb") as f:
                    f.write(file_res.content)
                downloaded_files.append(name)
            else:
                print(f"❌ Failed to download {name}: {file_res.status_code}")
    logger.info("testing 2222")

    return {
        "message": "✅ Download completed",
        "files": downloaded_files
    }
INDEX_DIR = "indexdir"

# -----------------------------
# helper: clean token
# -----------------------------
def clean_token(t: str) -> str:
    """Normalize token: remove special chars except * and -"""
    if not t:
        return ""
    return re.sub(r'[^A-Za-z0-9*-]', '', t).lower()

# -----------------------------
# CONFIGURATION FUNCTION
# -----------------------------
# tune these as needed
FILELOCK_POLL_INTERVAL = 0.2   # seconds between attempts to acquire lock
FILELOCK_TIMEOUT = 30          # overall seconds to wait for the lock

# --------------------- FILE LOCK HELPERS ---------------------
def _acquire_file_lock(lock_path, timeout=FILELOCK_TIMEOUT, poll_interval=FILELOCK_POLL_INTERVAL):
    start = time.time()
    fh = open(lock_path, "a+")
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except BlockingIOError:
            if (time.time() - start) >= timeout:
                fh.close()
                raise TimeoutError(f"Timeout waiting for file lock {lock_path}")
            time.sleep(poll_interval)
        except Exception:
            fh.close()
            raise


def _release_file_lock(fh):
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fh.close()
    except Exception:
        pass


# --------------------- INDEX CREATION ---------------------
def get_or_create_index(index_dir):
    """
    Create or open a Whoosh index at the given path.
    """
    schema = Schema(
        id=ID(stored=True, unique=True),
        question=TEXT(stored=True),
        answer=TEXT(stored=True),
        transcript_name=TEXT(stored=True),
        witness_name=TEXT(stored=True),
        cite=TEXT(stored=True),
    )

    if not os.path.exists(index_dir):
        os.makedirs(index_dir)

    if not index.exists_in(index_dir):
        ix = index.create_in(index_dir, schema)
        logger.info(f"✅ Created new Whoosh index at: {index_dir}")
    else:
        ix = index.open_dir(index_dir)
        logger.info(f"📂 Opened existing Whoosh index at: {index_dir}")

    return ix


def index_documents(ix, docs_list):
    """
    Index a list of documents into the Whoosh index.
    """
    if not docs_list:
        logger.warning("⚠️ No documents to index.")
        return

    writer = ix.writer()
    for d in docs_list:
        writer.update_document(
            id=d["id"],
            question=d["question"],
            answer=d["answer"],
            transcript_name=d["transcript_name"],
            witness_name=d["witness_name"],
            cite=d["cite"],
        )
    writer.commit()
    logger.info(f"✅ Indexed {len(docs_list)} documents into Whoosh index.")


# --------------------- SEARCH FUNCTION ---------------------

def search_documents(ix, q_text_field_map, mode="fuzzy", max_edits=2, join_with="AND",
                     page=1, page_size=200):
    """
    Whoosh search function with pagination.
    - q_text_field_map: dict mapping query_text -> list of fields
        e.g., {"Joey": ["transcript_name"], "some question": ["question", "answer"]}
    - Supports fuzzy, boolean, and exact modes.
    - Returns documents matching all query_text/field groups (AND across groups).
    """

    results = []
    total_results = 0
    if not q_text_field_map:
        q_text_field_map = {"": ["question", "answer"]}  # default: all docs
    logger.info(f"qqqqqqqqqqqqqqqqqqqqq00000000000000000 | field_queries={q_text_field_map}")

    with ix.searcher() as searcher:

        def build_hit(hit):
            return {
                "id": hit.get("id"),
                "transcript_name": hit.get("transcript_name", ""),
                "witness_name": hit.get("witness_name", ""),
                "question": hit.get("question", ""),
                "answer": hit.get("answer", ""),
                "cite": hit.get("cite", ""),
            }

        def make_query(text, fields):
            clean_terms = [t for t in re.split(r'\s+', text) if t]
            if not clean_terms:
                return Every()
            logger.info(f"🧩 clean_terms={clean_terms}")

            if mode.lower() == "fuzzy":
                queries = []
                for term in clean_terms:
                    t = term.lower()
                    if t.endswith("*"):
                        base = t.rstrip("*")
                        if base:
                            queries.append(And([Prefix(f, base) for f in fields]))
                        continue
                    if re.search(r'\d', t):
                        continue
                    edits = max_edits if len(t) >= 4 else 1
                    queries.append(And([FuzzyTerm(f, t, maxdist=edits) for f in fields]))
                return And(queries) if queries else None

            elif mode.lower() == "boolean":
                parser = MultifieldParser(fields, schema=ix.schema, group=AndGroup)
                qstring = text if re.search(r'\b(AND|OR|NOT)\b', text, re.I) \
                    else f" {join_with} ".join(clean_terms)
                return parser.parse(qstring)

            else:  # exact
                parser = MultifieldParser(fields, schema=ix.schema, group=AndGroup)
                return parser.parse(f'"{" ".join(clean_terms)}"')

        logger.info(f"🔍 q_text_field_map = {q_text_field_map}")

        # -------- COMBINE QUERIES WITH AND --------
        field_queries = []
        for text, fields in q_text_field_map.items():
            q = make_query(text, fields)
            logger.info(f"🧩 Built query for {text=} {fields=} → {q}")
            if q is not None:
                field_queries.append(q)

        # 🔹 Combine: AND all queries (so q1 & q3 must both match)
        if not field_queries:
            final_query = Every()
        else:
            final_query = And(field_queries)

        logger.info(f"✅ FINAL QUERY → {final_query}")
            # ✅ AND across all query groups
            final_query = And(field_queries)
            logger.info("qqqqqqqqqqqqqqqqqqqqq222222222222222222", final_query)
            logger.info(f"qqqqqqqqqqqqqqqqqqqqq222222222222222222 | final_query={final_query}")

        # -------- PAGINATED SEARCH --------
        try:
            whoosh_page = searcher.search_page(final_query, page, pagelen=page_size)
            for hit in whoosh_page:
                results.append(build_hit(hit))
            total_results = whoosh_page.total
        except ValueError:
            results = []
            total_results = 0

    return results, total_results
