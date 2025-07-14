from django.http import JsonResponse
from .serializers import TranscriptEntrySerializer
from elasticsearch import Elasticsearch
# from rest_framework.decorators import api_view
from rest_framework.response import Response
# from elasticsearch import helpers
import inflect

p = inflect.engine()

es = Elasticsearch(
    "http://localhost:9200",
    headers={"Accept": "application/vnd.elasticsearch+json; compatible-with=8"}
)

# @api_view(["GET"])
# def fetch_and_index(request):
#     if es.indices.exists(index="transcripts"):
#         es.indices.delete(index="transcripts")
#     entries = TranscriptEntry.objects.all()
#     serializer = TranscriptEntrySerializer(entries, many=True)

#     actions = [
#         {
#             "_index": "transcripts",
#             "_id": record["id"],  # Use primary key to prevent duplicates
#             "_source": record
#         }
#         for record in serializer.data
#     ]

#     try:
#         helpers.bulk(es, actions)
#         return Response({"status": "indexed", "count": len(actions)})
#     except Exception as e:
#         return Response({"error": str(e)}, status=500)


def expand_word_forms(word):
    forms = {word}
    if p.singular_noun(word):
        forms.add(p.singular_noun(word))  # plural to singular
    else:
        forms.add(p.plural(word))  # singular to plural
    return list(forms)

def search_testimonies(request):
    query = request.GET.get("q", "").strip()
    mode = request.GET.get("mode", "exact").lower()
    if not query:
        return Response({"error": "Missing search query (?q=...)"}, status=400)

    fields = ["question", "answer", "cite", "filename"]

    if mode == "fuzzy":
        words = query.split()
        expanded_terms = []
        for word in words:
            expanded_terms.extend(expand_word_forms(word))

        es_query = {
            "query": {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": term,
                                "fields": fields,
                                "fuzziness": "AUTO"
                            }
                        } for term in expanded_terms
                    ]
                }
            }
        }


    elif mode == "boolean":
        import re
        fields = ["question", "answer", "cite", "filename"]

        # Proximity logic
        if "/s" in query:
            parts = [part.strip() for part in query.split("/s")]
            if len(parts) == 2:
                term1, term2 = parts
                es_query = {
                    "query": {
                        "bool": {
                            "should": [
                                {
                                    "match_phrase": {
                                        field: {
                                            "query": f"{term1} {term2}",
                                            "slop": 5
                                        }
                                    }
                                } for field in fields
                            ]
                        }
                    }
                }
            else:
                return Response({"error": "Invalid proximity format. Use: word1 /s word2"}, status=400)
        else:
            # Split out NOT terms
            not_pattern = r"\bNOT\s+(\w+)"
            not_terms = re.findall(not_pattern, query, flags=re.IGNORECASE)
            cleaned_query = re.sub(not_pattern, "", query, flags=re.IGNORECASE).strip()

            # Construct bool query
            bool_query = {"must_not": []}

            if cleaned_query:
                bool_query["must"] = [
                    {
                        "query_string": {
                            "query": cleaned_query,
                            "fields": fields,
                            "default_operator": "AND"
                        }
                    }
                ]

            if not_terms:
                for term in not_terms:
                    bool_query["must_not"].append({
                        "multi_match": {
                            "query": term,
                            "fields": fields
                        }
                    })

            es_query = {"query": {"bool": bool_query}}
    else:
        search_term = query.strip()
        es_query = {
            "query": {
                "bool": {
                    "should": [
                        {"match_phrase": {field: search_term}} for field in fields
                    ]
                }
            }
        }

    

    # Perform the search
    try:
        print("hello3")
        response = es.search(index="transcripts", body=es_query)
        
        results = [hit["_source"] for hit in response["hits"]["hits"]]
        return Response({
            "query": query,
            "mode": mode,
            "count": len(results),
            "results": results
        })
    except Exception as e:
        return Response({"error": str(e)}, status=500)
    


