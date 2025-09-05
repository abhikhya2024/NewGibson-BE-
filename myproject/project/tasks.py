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

    # preload transcripts from all databases
    transcripts = {}
    for db in DB_NAMES:
        for t in Transcript.objects.using(db).all():
            transcripts[t.name] = (t, db)   # keep track of db also

    # preload existing testimonies from all databases
    existing = set()
    for db in DB_NAMES:
        existing |= set(
            Testimony.objects.using(db).values_list(
                "question", "answer", "cite", "index", "file_id"
            )
        )

    for item in results:
        item.pop("id", None)
        txt_filename = item.get("filename")
        transcript_info = transcripts.get(txt_filename)

        if not transcript_info:
            skipped += 1
            continue

        transcript, db = transcript_info

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
                file=transcript
            ))

    # insert testimonies into *same DB as transcript*
    for db in DB_NAMES:
        objs_for_db = [obj for obj in qa_objects if obj.file._state.db == db]
        if objs_for_db:
            Testimony.objects.using(db).bulk_create(objs_for_db, batch_size=5000)

    return {
        "inserted": len(qa_objects),
        "skipped": skipped,
        "total": len(results)
    }


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
                },
            }
            actions.append(doc)

            if len(actions) >= batch_size:
                success, errors = bulk(es, actions)
                total_indexed += success
                if errors:
                    logger.error(f"⚠️ Bulk errors for {source_label}: {errors[:3]}")  # log first 3 errors
                logger.info(f"✅ Bulk indexed {success} testimonies from {source_label}")
                actions.clear()

        except Exception as e:
            logger.error(f"❌ Error indexing {source_label} testimony ID {testimony.id}: {str(e)}")

    if actions:
        success, errors = bulk(es, actions)
        total_indexed += success
        if errors:
            logger.error(f"⚠️ Final bulk errors for {source_label}: {errors[:3]}")
        logger.info(f"✅ Bulk indexed remaining {success} testimonies from {source_label}")

    if total_indexed == 0:
        logger.warning(f"⚠️ No testimonies found in DB alias '{db_alias}'")

    return total_indexed


@shared_task
def index_task(index_name):
    """
    Celery task to run Elasticsearch indexing in background.
    """
    try:
        logger.info(f"📂 Starting indexing task for index '{index_name}'")

        total = 0
        total += index_from_db("default", "ruck", index_name)
        total += index_from_db("cummings", "cummings", index_name)
        total += index_from_db("prochaska", "prochaska", index_name)
        total += index_from_db("proctor", "proctor", index_name)

        logger.info(f"🎉 Indexing task completed successfully, total indexed: {total}")
        return {"status": "success", "indexed": total}

    except Exception as e:
        logger.error(f"❌ Indexing task failed: {str(e)}")
        return {"status": "error", "message": str(e)}