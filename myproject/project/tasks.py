from celery import shared_task
from .models import Transcript, Testimony
from .sharepoint_utils import fetch_json_files_from_sharepoint

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
