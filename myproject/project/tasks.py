from celery import shared_task
from .models import Transcript, Testimony, Witness
from .sharepoint_utils import fetch_json_files_from_sharepoint
from elasticsearch import Elasticsearch
from datetime import datetime, timezone
from rest_framework.response import Response
from rest_framework import status, permissions
es = Elasticsearch("http://localhost:9200")  # Adjust if needed

@shared_task
def save_testimony_task():
    results = fetch_json_files_from_sharepoint()
    qa_objects = []
    skipped = 0

    transcripts = {t.name: t for t in Transcript.objects.all()}  # preload transcripts
    existing = set(Testimony.objects.values_list(
        "question", "answer", "cite", "index", "file_id"
    ))

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

    Testimony.objects.bulk_create(qa_objects, batch_size=5000)
    return {
        "inserted": len(qa_objects),
        "skipped": skipped,
        "total": len(results)
    }

@shared_task
def create_index_task():
    INDEX_NAME = "transcripts"

    # Step 1: Define mapping
    mapping = {
        "mappings": {
            "properties": {
                "id": {"type": "integer"},
                "question": {"type": "text"},
                "answer": {"type": "text"},
                "cite": {"type": "text"},
                "transcript_name": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}}
                },
                "witness_name": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}}
                },
                "type": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}}
                },
                "alignment": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}}
                },
                "source": {
                    "type": "keyword"
                },
                "commenter_emails": {
                    "type": "nested",
                    "properties": {
                        "name": {"type": "text"},
                        "email": {"type": "keyword"}
                    }
                },
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis"
                }
            }
        }
    }

    try:
        if es.indices.exists(index=INDEX_NAME):
            es.indices.delete(index=INDEX_NAME)

        es.indices.create(index=INDEX_NAME, body=mapping)
        print(f"✅ Created new index: '{INDEX_NAME}'")

        # Indexing logic from multiple databases
        def index_from_db(db_alias, source_label):
            testimonies = Testimony.objects.using(db_alias).select_related("file").all()
            for testimony in testimonies:
                try:
                    transcript = Transcript.objects.using(db_alias).filter(id=testimony.file_id).first()
                    witness = Witness.objects.using(db_alias).filter(file_id=testimony.file_id).first()

                    doc = {
                        "id": testimony.id,
                        "question": testimony.question or "",
                        "answer": testimony.answer or "",
                        "cite": testimony.cite or "",
                        "transcript_name": transcript.name if transcript else "",
                        "witness_name": witness.fullname if witness else "",
                        "type": witness.type.type if (witness and witness.type) else "",
                        "alignment": str(witness.alignment) if (witness and witness.alignment) else "",
                        "source": source_label,
                        "commenter_emails": [],  # 🔹 Empty list so field always exists
                        "created_at": datetime.now(timezone.utc).isoformat()

                    }

                    es.index(index=INDEX_NAME, id=f"{source_label}_{testimony.id}", body=doc)
                    print(f"📌 Indexed {source_label} testimony ID {testimony.id}")

                except Exception as e:
                    print(f"❌ Error indexing {source_label} testimony ID {testimony.id}: {str(e)}")

        # Step 2: Index from both databases
        index_from_db("default", "proctor")
        # index_from_db("farrar", "farrar")
        return Response({"message": "✅ Indexing complete."}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
