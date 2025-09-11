from celery import shared_task
from .models import Transcript, Testimony, Witness
from .sharepoint_utils import fetch_json_files_from_sharepoint
from elasticsearch import Elasticsearch
from datetime import datetime, timezone
from rest_framework.response import Response
from rest_framework import status, permissions
es = Elasticsearch("http://localhost:9200")  # Adjust if needed
import logging
from elasticsearch.helpers import bulk

logger = logging.getLogger("logging_handler")  # 👈 custom logger name
DB_NAMES = ['default', 'cummings', 'prochaska', 'proctor', 'ruckd']  # 5 databases
INDEX_NAME = "testimonies"

@shared_task
def save_testimony_task():
    results = fetch_json_files_from_sharepoint()
    qa_objects = []
    skipped = 0

    # preload transcripts from default database
    transcripts = {t.name: t for t in Transcript.objects.all()}

    # preload existing testimonies from default database
    existing = set(
        Testimony.objects.values_list(
            "question", "answer", "cite", "index", "file_id"
        )
    )

    for item in results:
        item.pop("id", None)
        txt_filename = item.get("filename")
        transcript = transcripts.get(txt_filename)

        if not transcript:
            skipped += 1
            continue

        qa_key = (
            item.get("question"),
            item.get("answer"),
            item.get("cite"),
            item.get("index"),
            transcript.id,
        )

        if qa_key not in existing:
            qa_objects.append(Testimony(
                question=item.get("question"),
                answer=item.get("answer"),
                cite=item.get("cite"),
                index=item.get("index"),
                file=transcript,
            ))

    # insert testimonies into default DB
    if qa_objects:
        Testimony.objects.bulk_create(qa_objects, batch_size=5000)

    return {
        "inserted": len(qa_objects),
        "skipped": skipped,
        "total": len(results),
    }

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
                    "transcript_date":transcript.transcript_date,
                    "case_name": transcript.case_name
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

def index_transcripts(db_alias, source_label, index_name, batch_size=500):
    """
    Stream transcripts from the database and bulk index into Elasticsearch.
    """
    transcripts = (
        Transcript.objects.using(db_alias)
        .iterator(chunk_size=batch_size)
    )

    total_indexed = 0
    actions = []

    for transcript in transcripts:
        try:
            doc = {
                "_index": index_name,
                "_id": f"{source_label}_{transcript.id}",
                "_source": {
                    "id": transcript.id,
                    "name": transcript.name or "",
                    "transcript_date": (
                        transcript.transcript_date.isoformat() 
                        if transcript.transcript_date else None
                    ),
                    "case_name": transcript.case_name or "",
                    "file": str(transcript.file) if transcript.file else None,
                    "created_by": transcript.created_by if hasattr(transcript, "created_by") else None,
                    "project": transcript.project if hasattr(transcript, "project") else None,
                    "created_at": (
                        transcript.created_at.isoformat() 
                        if transcript.created_at else datetime.now(timezone.utc).isoformat()
                    ),
                    "updated_at": (
                        transcript.updated_at.isoformat() 
                        if transcript.updated_at else datetime.now(timezone.utc).isoformat()
                    ),
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
        logger.warning(f"⚠️ No transcripts found in DB alias '{db_alias}'")

    logger.info(f"🎯 Finished indexing {total_indexed} transcripts from {source_label}")
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
        total += index_transcripts("default", "docsgibsondemo", index_name)
        # total += index_from_db("cummings", "cummings", index_name)
        # total += index_from_db("prochaska", "prochaska", index_name)
        # total += index_from_db("proctor", "proctor", index_name)

        logger.info(f"🎉 Indexing task completed successfully, total indexed: {total}")
        return {"status": "success", "indexed": total}

    except Exception as e:
        logger.error(f"❌ Indexing task failed: {str(e)}")
        return {"status": "error", "message": str(e)}