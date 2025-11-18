from celery import shared_task
from .models import Transcript, Testimony, Witness
from .sharepoint_utils import fetch_json_files_from_sharepoint,normalize_index_text, download_all_transcripts, get_or_create_index, index_documents
from elasticsearch import Elasticsearch
from datetime import datetime, timezone
from rest_framework.response import Response
from rest_framework import status, permissions
es = Elasticsearch("http://localhost:9200")  # Adjust if needed
import logging
from elasticsearch.helpers import bulk
from collections import defaultdict
import os

logger = logging.getLogger("logging_handler")  # 👈 custom logger name
DB_NAMES = ['default']  # 5 databases
INDEX_NAME = "testimonies"
BASE_DIR = "/var/www/gibson-be/NewGibson-BE-/myproject/project"
INDEX_DIR = os.path.join(BASE_DIR, "whoosh_index")
# ✅ Helper to split dictionary into chunks of N transcripts
def chunk_transcripts(transcripts_dict, size=10):
    items = list(transcripts_dict.items())
    for i in range(0, len(items), size):
        yield dict(items[i:i + size])

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def build_whoosh_index(self):
    """
    Celery task to build/update the Whoosh index from testimonies.
    """
    try:
        # Step 1: Fetch testimonies
        testimonies = Testimony.objects.select_related("file").all()
        docs_list = []
        for t in testimonies:
            transcript_name = t.file.name if t.file else ""
            witness_name = t.witness_name or ""
            question = t.question or ""
            answer = t.answer or ""
            cite = t.cite or ""
            web_url = t.web_url or ""
            created_at = t.created_at
            project_name = t.project_name
            if created_at and created_at.tzinfo:
                created_at = created_at.replace(tzinfo=None)

            if question.strip() or answer.strip():
                docs_list.append({
                    "id": str(t.id),
                    "transcript_name": transcript_name.strip(),
                    "witness_name": witness_name.strip(),
                    "question": question.strip(),
                    "answer": answer.strip(),
                    "cite": cite.strip(),
                    "transcript_name_exact": transcript_name.strip(),
                    "created_at": created_at,
                    "web_url": web_url,
                    "project_name": project_name,
                    "project_name_search": normalize_index_text(project_name or "")
                })

        if not docs_list:
            logger.warning("⚠️ No testimonies found to index.")
            return "No testimonies to index."

        # Step 2: Get or create index
        ix = get_or_create_index(INDEX_DIR)

        # Step 3: Index documents
        index_documents(ix, docs_list)

        logger.info(f"✅ Whoosh index built successfully with {len(docs_list)} documents.")
        return f"Indexed {len(docs_list)} documents successfully."

    except Exception as e:
        logger.error("❌ Error building index: %s", str(e))
        self.retry(exc=e)
# ✅ Main Celery Task
@shared_task
def save_testimony_task():
    try:
        logger.info("🚀 Starting testimony save task...")

        results = fetch_json_files_from_sharepoint()
        logger.info(f"📦 Total QA pairs fetched: {len(results)}")

        # Group all fetched records by transcript filename
        transcript_groups = defaultdict(list)
        for item in results:
            transcript_groups[item["filename"]].append(item)

        inserted_total = 0
        skipped_total = 0

        # Process transcripts in batches of 10 at a time
        for batch in chunk_transcripts(transcript_groups, size=10):
            logger.info(f"🧩 Processing batch with {len(batch)} transcripts...")

            batch_inserted, batch_skipped = process_transcript_batch(batch)
            inserted_total += batch_inserted
            skipped_total += batch_skipped

            logger.info(f"✅ Finished batch: inserted={batch_inserted}, skipped={batch_skipped}")

        logger.info(f"🎯 Task completed. Total inserted={inserted_total}, skipped={skipped_total}")
        return {"inserted": inserted_total, "skipped": skipped_total}

    except Exception as e:
        logger.exception("❌ save_testimony_task failed:")
        return {"error": str(e)}


# ✅ Helper function to process each transcript batch
def process_transcript_batch(batch):
    qa_objects = []
    skipped = 0

    # preload transcripts & witnesses
    transcripts = {}
    for db in DB_NAMES:
        for t in Transcript.objects.using(db).all():
            transcripts[t.name] = (t, db)

    witnesses_map = {}
    for db in DB_NAMES:
        for w in Witness.objects.using(db).all():
            if w.file_id not in witnesses_map:
                witnesses_map[w.file_id] = []
            if w.fullname:
                witnesses_map[w.file_id].append(w.fullname)

    existing = set()
    for db in DB_NAMES:
        existing |= set(
            Testimony.objects.using(db).values_list(
                "question", "answer", "cite", "index", "file_id"
            )
        )

    for filename, items in batch.items():
        transcript_info = transcripts.get(filename)
        if not transcript_info:
            skipped += len(items)
            continue

        transcript, db = transcript_info
        witness_names = witnesses_map.get(transcript.id, [])
        witness_name_str = ", ".join(witness_names) if witness_names else None

        for item in items:
            qa_key = (
                item.get("question"),
                item.get("answer"),
                item.get("cite"),
                item.get("index"),
                transcript.id
            )
            if qa_key not in existing:
                qa_objects.append(Testimony(
                    question=item.get("question"),
                    answer=item.get("answer"),
                    cite=item.get("cite"),
                    index=item.get("index"),
                    file=transcript,
                    witness_name=witness_name_str,
                    project_name=item.get("project_name") 
                ))
            else:
                skipped += 1

    # Insert in bulk per DB
    for db in DB_NAMES:
        objs_for_db = [obj for obj in qa_objects if obj.file._state.db == db]
        if objs_for_db:
            Testimony.objects.using(db).bulk_create(objs_for_db, batch_size=5000)

    return len(qa_objects), skipped

def safe_bulk(client, actions, source_label):
    """
    Run Elasticsearch bulk safely and log errors.
    """
    success, errors = bulk(client, actions, raise_on_error=False)
    logger.info(f"✅ Indexed {success} docs from {source_label}")
    if errors:
        logger.error(f"⚠️ {len(errors)} bulk errors from {source_label}")
        for err in errors[:3]:  # log only first 3 for readability
            logger.error(err)
    return success, errors

def index_from_db(db_alias, source_label, index_name, batch_size=500):
    """
    Stream testimonies from the database and bulk index into Elasticsearch.
    """
    testimonies = (
        Testimony.objects.using(db_alias)
        .select_related("file")
        .iterator(chunk_size=batch_size)
    )

    total_indexed = 0
    actions = []

    for testimony in testimonies:
        try:
            transcript = Transcript.objects.using(db_alias).filter(id=testimony.file_id).first()
            witness = Witness.objects.using(db_alias).filter(file_id=testimony.file_id).first()

            doc = {
                "_index": index_name,
                "_id": f"{source_label}_{testimony.id}",
                "_source": {
                    "id": testimony.id,
                    "question": testimony.question or "",
                    "answer": testimony.answer or "",
                    "cite": testimony.cite or "",
                    "transcript_name": transcript.name if transcript else "",
                    "witness_name": witness.fullname if witness else "",
                    "type": witness.type.type if (witness and witness.type) else "",
                    "alignment": str(witness.alignment) if (witness and witness.alignment) else "",
                    "source": source_label,
                    "commenter_emails": [],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "transcript_date": transcript.transcript_date,
                },
            }
            actions.append(doc)

            # Flush in batches
            if len(actions) >= batch_size:
                success, _ = safe_bulk(es, actions, source_label)
                total_indexed += success
                actions.clear()

        except Exception as e:
            logger.error(f"❌ Error indexing {source_label} testimony ID {testimony.id}: {str(e)}")

    # Final flush
    if actions:
        success, _ = safe_bulk(es, actions, source_label)
        total_indexed += success

    if total_indexed == 0:
        logger.warning(f"⚠️ No testimonies found in DB alias '{db_alias}'")

    logger.info(f"🎯 Finished indexing {total_indexed} testimonies from {source_label}")
    return total_indexed


def transcript_index_from_db(db_alias, source_label, index_name, batch_size=500):
    """
    Stream transcript from the database and bulk index into Elasticsearch.
    """
    transcripts = (
        Transcript.objects.using(db_alias)
        .iterator(chunk_size=batch_size)
    )

    total_indexed = 0
    actions = []

    for transcript in transcripts:
        try:
            # transcript = Transcript.objects.using(db_alias).filter(id=transcript.file_id).first()
            # witness = Witness.objects.using(db_alias).filter(file_id=transcript.file_id).first()
            witness = Witness.objects.filter(
                file__name=transcript.name
            ).first()
            doc = {
                "_index": index_name,
                "_id": f"{source_label}_{transcript.id}",
                "_source": {
                    "id": transcript.id,
                    "transcript_name": transcript.name if transcript else "",
                    "case_name": transcript.case_name if transcript else "",
                    "witness_name": witness.fullname if witness else "",
                    "source": source_label,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "transcript_date": transcript.transcript_date,
                },
            }
            actions.append(doc)

            # Flush in batches
            if len(actions) >= batch_size:
                success, _ = safe_bulk(es, actions, source_label)
                total_indexed += success
                actions.clear()

        except Exception as e:
            logger.error(f"❌ Error indexing {source_label} transcript ID {transcript.id}: {str(e)}")

    # Final flush
    if actions:
        success, _ = safe_bulk(es, actions, source_label)
        total_indexed += success

    if total_indexed == 0:
        logger.warning(f"⚠️ No testimonies found in DB alias '{db_alias}'")

    logger.info(f"🎯 Finished indexing {total_indexed} testimonies from {source_label}")
    return total_indexed

@shared_task
def index_task(index_name):
    """
    Celery task to run Elasticsearch indexing in background.
    """
    try:
        logger.info(f"📂 Starting indexing task for index '{index_name}'")

        total = 0
        total += index_from_db("default", "docsgibsondemo", index_name)
        # total += index_from_db("cummings", "cummings", index_name)
        # total += index_from_db("prochaska", "prochaska", index_name)
        # total += index_from_db("proctor", "proctor", index_name)

        logger.info(f"🎉 Indexing task completed successfully, total indexed: {total}")
        return {"status": "success", "indexed": total}

    except Exception as e:
        logger.error(f"❌ Indexing task failed: {str(e)}")
        return {"status": "error", "message": str(e)}

@shared_task
def index_transcript_task(index_name):
    """
    Celery task to run Elasticsearch indexing in background.
    """
    try:
        logger.info(f"📂 Starting indexing task for index '{index_name}'")

        total = 0
        total += transcript_index_from_db("default", "docsgibsondemo", index_name)
        # total += index_from_db("cummings", "cummings", index_name)
        # total += index_from_db("prochaska", "prochaska", index_name)
        # total += index_from_db("proctor", "proctor", index_name)

        logger.info(f"🎉 Indexing task completed successfully, total indexed: {total}")
        return {"status": "success", "indexed": total}

    except Exception as e:
        logger.error(f"❌ Indexing task failed: {str(e)}")
        return {"status": "error", "message": str(e)}
  
@shared_task
def download_transcripts_task():
    """Background task to download all SharePoint transcripts"""
    return download_all_transcripts()  # this returns your dict {"message", "files"}