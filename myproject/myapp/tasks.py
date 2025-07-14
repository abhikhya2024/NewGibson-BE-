from myapp.models import TranscriptEntry
from .sharepoint_utils import fetch_json_files_from_sharepoint

def save_json_files_to_postgres():
    total = 0
    for filename, data_list in fetch_json_files_from_sharepoint():
        print(f"Saving: {filename} with {len(data_list)} records")
        for record in data_list:
            TranscriptEntry.objects.create(
                question=record.get("question"),
                answer=record.get("answer"),
                cite=record.get("cite"),
                filename=filename
            )
            total += 1
    print(f"✅ Inserted {total} records.")
