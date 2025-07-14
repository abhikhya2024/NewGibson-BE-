from elasticsearch import Elasticsearch

# Connect to local Elasticsearch (ensure it's running)
es = Elasticsearch(
    "http://localhost:9200",
    headers={"Accept": "application/vnd.elasticsearch+json; compatible-with=8"}
)
def save_to_elasticsearch(data, filename):
    for record in data:
        record["filename"] = filename
        es.index(index="transcripts", id=record["id"], document=record)