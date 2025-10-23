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
from whoosh.qparser import MultifieldParser, OrGroup
from whoosh.query import FuzzyTerm, Or as OrQuery, And as AndQuery, Prefix
from rapidfuzz import fuzz
import shutil
import time
from whoosh.index import LockError
import fcntl
from whoosh.fields import Schema, TEXT, ID

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

def _acquire_file_lock(lock_path, timeout=FILELOCK_TIMEOUT, poll_interval=FILELOCK_POLL_INTERVAL):
    """Open lock file and acquire exclusive flock. Returns open file handle (must be closed to release)."""
    start = time.time()
    fh = open(lock_path, "a+")  # keep file descriptor open, create file if missing
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # acquired
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

def configure_index(docs_list, index_dir, lock_filename=".whoosh_index_lock"):
    """
    Create/open Whoosh index and add docs_list while holding an OS-level file lock
    so only one process at a time writes the index.
    """
    os.makedirs(index_dir, exist_ok=True)
    lock_path = os.path.join(index_dir, lock_filename)

    # Prepare schema
    schema = Schema(
        id=ID(stored=True, unique=True),
        question=TEXT(stored=True),
        answer=TEXT(stored=True),
        cite=TEXT(stored=True),
        transcript_name=TEXT(stored=True),
        witness_name=TEXT(stored=True),
    )

    # Validate/normalize docs_list
    valid_docs = []
    for doc in docs_list:
        try:
            _id = str(doc.get("id", "")).strip()
            _question = str(doc.get("question", "")).strip()
            _answer = str(doc.get("answer", "")).strip()
            _cite = str(doc.get("cite", "")).strip()
            _transcript_name = str(doc.get("transcript_name", "")).strip()
            _witness_name = str(doc.get("witness_name", "")).strip()
        except Exception:
            continue

        # Require an id and at least one non-empty searchable field
        if not _id:
            continue

        if not (_question or _answer or _cite or _transcript_name or _witness_name):
            # skip documents that have no useful content to index
            continue

        valid_docs.append({
            "id": _id,
            "question": _question,
            "answer": _answer,
            "cite": _cite,
            "transcript_name": _transcript_name,
            "witness_name": _witness_name,
        })

    # ✅ Add your debug prints here
    print(f"📦 Indexing {len(valid_docs)} documents...")
    logger.info(f"📦 Indexing {len(valid_docs)} documents...//////////////////////////////////////////////////")

    for d in valid_docs[:5]:
        print("   →", d)
        logger.info(f"📦 Indexing {d} documents...//////////////////////////////////////////////////")

        
    if not valid_docs:
        raise ValueError("No valid documents to index. Aborting to avoid Whoosh errors.")

    if not valid_docs:
        raise ValueError("No valid documents to index. Aborting to avoid Whoosh errors.")

    # Acquire host-level file lock so only one process builds/updates index at a time.
    fh = None
    try:
        fh = _acquire_file_lock(lock_path)   # may raise TimeoutError
        # At this point we hold the lock.
        # Create/open index safely (now only one process is here)
        if not index.exists_in(index_dir):
            logger.info("⚙️ Creating new Whoosh index...")
            ix = index.create_in(index_dir, schema)
        else:
            ix = index.open_dir(index_dir)

        # Write documents (use ix.writer() which still uses its own Whoosh locking)
        with ix.writer() as writer:
            for doc in valid_docs:
                writer.update_document(
                    id=doc["id"],
                    question=doc.get("question", ""),
                    answer=doc.get("answer", ""),
                    cite=doc.get("cite", ""),
                    transcript_name=doc.get("transcript_name", ""),
                    witness_name=doc.get("witness_name", ""),
                )

        logger.info(f"📦{ix} documents...//////////////////////////////////////////////////")

        # done - release lock in finally
        return ix

    except TimeoutError as te:
        # Could not acquire file lock in time
        print("❌ Timeout acquiring index file lock:", str(te))
        traceback.print_exc()
        raise
    except Exception:
        print("❌ Unexpected error in configure_index:")
        traceback.print_exc()
        raise
    finally:
        if fh:
            _release_file_lock(fh)

# -------------------------------
# Search function
# -------------------------------
def search_documents(ix, query_text, mode="fuzzy", max_edits=2, join_with="AND"):
    query_text = (query_text or "").strip()
    if not query_text:
        print("Empty query.")
        return []

    raw_terms = [t for t in re.split(r'\s+', query_text) if t]
    clean_terms = [t for t in raw_terms if t]
    logger.info(f"Clean terms {raw_terms} and {clean_terms}")
    results = []
    with ix.searcher() as searcher:
        parser = MultifieldParser(
            ["question", "answer", "cite", "transcript_name", "witness_name"],
            schema=ix.schema,
            group=OrGroup,
        )

        # ---------------- FUZZY MODE ----------------
        if mode == "fuzzy":
            queries = []
            logger.info(f"Inside fuzzy")

            for term in clean_terms:
                if term.endswith("*"):
                    base = term.rstrip("*")
                    if base:
                        queries.append(OrQuery([
                            Prefix("question", base),
                            Prefix("answer", base),
                            Prefix("cite", base),
                            Prefix("transcript_name", base),
                            Prefix("witness_name", base),
                        ]))
                    continue
                if re.search(r'\d', term):
                    continue
                edits = max_edits if len(term) >= 4 else min(1, max_edits)
                queries.append(OrQuery([
                    FuzzyTerm("question", term, maxdist=edits),
                    FuzzyTerm("answer", term, maxdist=edits),
                    FuzzyTerm("cite", term, maxdist=edits),
                    FuzzyTerm("transcript_name", term, maxdist=edits),
                    FuzzyTerm("witness_name", term, maxdist=edits),
                ]))

            if queries:

                final_query = AndQuery(queries)
                logger.info(f"final_query {final_query} and {queries}")

                whoosh_results = searcher.search(final_query, limit=None)
                logger.info(f"whoosh_results {whoosh_results}")

            else:
                whoosh_results = searcher.search(parser.parse(""), limit=None)
                logger.info(f"whoosh_results {whoosh_results}")

            candidate_hits = [hit for hit in whoosh_results] if whoosh_results else []
            logger.info(f"candidate_hits {candidate_hits}")

           # Numeric ID substring search across all fields
            if any(re.search(r'\d', t) for t in clean_terms):
                all_docs = list(searcher.documents())
                for d in all_docs:
                    combined_fields = " ".join([
                        d.get("question", "").lower(),
                        d.get("answer", "").lower(),
                        d.get("cite", "").lower(),
                        d.get("transcript_name", "").lower(),
                        d.get("witness_name", "").lower(),
                    ])

                    if all(
                        (t in combined_fields or t.replace("-", "") in combined_fields.replace("-", ""))
                        for t in clean_terms if re.search(r'\d', t)
                    ):
                        candidate_hits.append(d)
            logger.info(f"candidate_hits {candidate_hits}")
            # Strict AND filter
            seen = set()
            for hit in candidate_hits:
                combined = " ".join([
                    hit.get("question", "").lower(),
                    hit.get("answer", "").lower(),
                    hit.get("cite", "").lower(),
                    hit.get("transcript_name", "").lower(),
                    hit.get("witness_name", "").lower(),
                ])                
                if all(
                    (t.rstrip("*") in combined)
                    or (t.replace("-", "").rstrip("*") in combined.replace("-", ""))
                    or (fuzz.partial_ratio(t.rstrip("*"), combined) >= 70)
                    for t in clean_terms
                ):
                    if hit["id"] not in seen:
                        seen.add(hit["id"])
                        results.append(hit)

        # ---------------- BOOLEAN MODE ----------------
        elif mode == "boolean":
            # If the query contains AND, OR, NOT, let Whoosh parse it directly
            if re.search(r'\b(AND|OR|NOT)\b', query_text, re.I):
                qstring = query_text  # Keep original boolean operators
            else:
                # If no explicit boolean operators, join terms with the default
                qstring = f" {join_with} ".join(clean_terms)

            # Parse with Whoosh
            q = parser.parse(qstring)
            whoosh_results = searcher.search(q, limit=None)

            candidate_hits = [hit for hit in whoosh_results] if whoosh_results else []

            # Strict post-filter (optional, keep fuzzy-like matching)
            results = []
            seen = set()
            for hit in candidate_hits:
                combined = " ".join([
                    hit.get("question", "").lower(),
                    hit.get("answer", "").lower(),
                    hit.get("cite", "").lower(),
                    hit.get("transcript_name", "").lower(),
                    hit.get("witness_name", "").lower(),
                ])
                if all(
                    (t.rstrip("*").lower() in combined)
                    or (t.replace("-", "").rstrip("*").lower() in combined.replace("-", ""))
                    for t in clean_terms
                ):
                    if hit["id"] not in seen:
                        seen.add(hit["id"])
                        results.append(hit)

            logger.info(f"results {results}")


        else:
            raise ValueError("Invalid search mode.")
    return results