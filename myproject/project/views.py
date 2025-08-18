from rest_framework import viewsets
from .models import Project, Comment, Highlights, Testimony, Transcript, Witness, WitnessType, WitnessAlignment, WitnessFiles
from .serializers import ProjectSerializer,CommentSerializer, TranscriptFuzzySerializer, WitnessFuzzySerializer, HighlightsSerializer, TestimonySerializer, CombinedSearchInputSerializer, TranscriptSerializer,TranscriptNameListInputSerializer, WitnessNameListInputSerializer, WitnessSerializer, WitnessAlignmentSerializer, WitnessTypeSerializer
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.decorators import action
from .sharepoint_utils import fetch_from_sharepoint, fetch_witness_names_and_transcripts, fetch_json_files_from_sharepoint, fetch_taxonomy_from_sharepoint
from user.models import User
from datetime import datetime
# from .paginators import CustomPageNumberPagination  # Import your pagination
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view
import inflect
from elasticsearch import Elasticsearch
from django.db.models import Q
from django.db.models.functions import Lower
import re
from user.serializers import UserSerializer
p = inflect.engine()
es = Elasticsearch("http://localhost:9200")  # Adjust if needed
from rest_framework.parsers import JSONParser
from dateutil.parser import parse as parse_date
from datetime import datetime, timezone
from django.db.models import Count


def expand_word_forms(word):
    forms = {word}
    if p.singular_noun(word):
        forms.add(p.singular_noun(word))  # plural to singular
    else:
        forms.add(p.plural(word))  # singular to plural
    return list(forms)



class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

class TranscriptViewSet(viewsets.ModelViewSet):
    queryset = Transcript.objects.all()
    serializer_class = TranscriptSerializer
    parser_classes = [MultiPartParser]  # 👈 required for form-data upload
    def list(self, request, *args, **kwargs):
        # Optional: Add filtering logic here
        transcripts = self.get_queryset()  # This is self.queryset

        # Serialize the data
        serializer = self.get_serializer(transcripts, many=True)

        # Return the data as a Response
        return Response({
            "count": transcripts.count(),
            "transcripts": serializer.data
        })

    @action(detail=False, methods=["post"], url_path="create-index")
    def create_index(self, request):
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
            index_from_db("default", "default")
            # index_from_db("farrar", "farrar")

            return Response({"message": "✅ Indexing complete."}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    @swagger_auto_schema(
        method='post',
        request_body=TranscriptFuzzySerializer,
        responses={200: TestimonySerializer(many=True)}
    )
    @action(detail=False, methods=["post"], url_path="get-transcripts",parser_classes=[JSONParser])
    def get_transcripts(self, request):
        search_term = request.data.get("transcript_name", "").strip()

        if not search_term:
            return Response({"matching_transcripts": []}, status=status.HTTP_200_OK)

        # Fuzzy match query on transcript_name field
        query = {
            "query": {
                "match": {
                    "transcript_name": {
                        "query": search_term,
                        "fuzziness": "AUTO"
                    }
                }
            },
            "aggs": {
                "unique_transcript_names": {
                    "terms": {
                        "field": "transcript_name.keyword",
                        "size": 1000
                    }
                }
            }
        }

        try:
            res = es.search(index="transcripts", body=query, size=1000)
            matches = [bucket["key"] for bucket in res["aggregations"]["unique_transcript_names"]["buckets"]]
            return Response({"matching_transcripts": matches}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    @swagger_auto_schema(
        method='post',
        request_body=WitnessFuzzySerializer,
        responses={200: TestimonySerializer(many=True)}
    )        
    @action(detail=False, methods=["post"], url_path="get-witnesses",parser_classes=[JSONParser])
    def get_witnesses(self, request):
        search_term = request.data.get("witness_name", "").strip().lower()

        if not search_term:
            return Response({"matching_witnesses": []}, status=status.HTTP_200_OK)

        # Fuzzy match query on transcript_name field
        query = {
            "query": {
                "match": {
                    "witness_name": {
                        "query": search_term,
                        "fuzziness": "AUTO"
                    }
                }
            },
            "aggs": {
                "unique_witness_names": {
                    "terms": {
                        "field": "witness_name.keyword",
                        "size": 1000
                    }
                }
            }
        }

        try:
            res = es.search(index="transcripts", body=query, size=1000)
            matches = [bucket["key"] for bucket in res["aggregations"]["unique_witness_names"]["buckets"]]
            return Response({"matching_witnesses": matches}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
      
    # def create(self, request, *args, **kwargs):
    #     files = request.FILES.getlist('files')  # Expecting 'files' key from FormData
    #     print(files)
        # for file in files:
            # trns = Transcript.objects.create()
            # witness = Witness.objects.create()

        # Single object create (default behavior)
        # return Response("Files Uploaded",status=201)
    # ✅ GET /transcript/save-transcripts → get names from SharePoint only
    @action(detail=False, methods=["get"], url_path="save-transcripts")   # Create post
    def save_transcripts(self, request):
        try:
            results = fetch_from_sharepoint()

            # ⚠️ Set default user and project manually or fetch them dynamically
            default_user = User.objects.first()  # Or filter by email etc.
            default_project = Project.objects.first()  # Or filter appropriately

            if not default_user or not default_project:
                return Response({"error": "User or Project not found."}, status=400)

            created = 0
            for item in results:
                transcript_name = item.get("transcript_name")
                transcript_date = item.get("transcript_date")
                transcript_date_obj = datetime.strptime(transcript_date, "%m-%d-%Y").date()

                if not (transcript_name and transcript_date):
                    continue

                # Avoid duplicates
                if not Transcript.objects.filter(
                    name=transcript_name,
                    transcript_date=transcript_date_obj,
                    created_by=default_user,
                    project=default_project
                ).exists():
                    Transcript.objects.create(
                        name=transcript_name,
                        transcript_date=transcript_date_obj,
                        created_by=default_user,
                        project=default_project
                    )
                    created += 1

            return Response({
                "status": "success",
                "inserted": created,
                "total_fetched": len(results)
            })

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# class TestimonyViewSet(viewsets.ModelViewSet):
#     queryset = Testimony.objects.all().order_by("id")
#     serializer_class = TestimonySerializer
#     # pagination_class = CustomPageNumberPagination

class TestimonyViewSet(viewsets.ModelViewSet):
    queryset = Testimony.objects.all().order_by("id")
    serializer_class = TestimonySerializer

    def list(self, request, *args, **kwargs):
        # Get offset and limit from query parameters
        try:
            offset = int(request.GET.get("offset", 0))
            limit = int(request.GET.get("limit", 100))  # default limit is 100
        except ValueError:
            return Response({"error": "Invalid offset or limit"}, status=400)

        queryset = self.filter_queryset(self.get_queryset())

        total_count = queryset.count()

        # Apply slicing using offset and limit
        paginated_queryset = queryset[offset:offset + limit]

        serializer = self.get_serializer(paginated_queryset, many=True)

        return Response({
            "offset": offset,
            "limit": limit,
            "total": total_count,
            "count": len(serializer.data),
            "results": serializer.data
        })
    @action(detail=False, methods=["get"], url_path="testimony-cnt-by-transcripts")
    def get(self, request):
        # Annotate each transcript with testimony count
        data = (
            Transcript.objects
            .annotate(testimony_count=Count('testimony_data'))
            .values('name', 'testimony_count')
        )

        return Response(list(data), status=status.HTTP_200_OK)    
# ✅ GET /testimony/save-testimony/ → get names from SharePoint only
    @action(detail=False, methods=["get"], url_path="save-testimony")
    def save_testimony(self, request):
        try:
            results = fetch_json_files_from_sharepoint()

            qa_objects = []
            skipped = 0

            for item in results:
                item.pop("id", None)
                txt_filename = item.get("filename")

                transcript = Transcript.objects.filter(name=txt_filename).first()
                if not transcript:
                    print(f"❌ Skipping again: No transcript found for {txt_filename}")
                    skipped += 1
                    continue

                question = item.get("question")
                answer = item.get("answer")
                cite = item.get("cite")
                index = item.get("index")

                if not Testimony.objects.filter(
                    question=question,
                    answer=answer,
                    cite=cite,
                    index=index,
                    file=transcript
                ).exists():
                    qa_objects.append(Testimony(
                        question=question,
                        answer=answer,
                        cite=cite,
                        index=index,
                        file=transcript
                    ))
                    print("inserted QA pair")

            Testimony.objects.bulk_create(qa_objects, batch_size=1000)

            return Response({
                "status": "success",
                "inserted": len(qa_objects),
                "skipped_due_to_missing_transcript": skipped,
                "total_fetched": len(results)
            })

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ✅ GET /testimony/search-testimony/ → get names from SharePoint only
    @action(detail=False, methods=["get"], url_path="search-testimony")
    def search_testimonies(self, request):        
        query = request.GET.get("q", "").strip()
        mode = request.GET.get("mode", "exact").lower()
        if not query:
            return Response({"error": "Missing search query (?q=...)"}, status=400)

        fields = ["question", "answer", "cite", "transcript_name"]

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
                not_pattern = r"\bNOT\s+(\w+)"
                not_terms = re.findall(not_pattern, query, flags=re.IGNORECASE)
                cleaned_query = re.sub(not_pattern, "", query, flags=re.IGNORECASE).strip()

                bool_query = {"must_not": []}
                if cleaned_query:
                    bool_query["must"] = [{
                        "query_string": {
                            "query": cleaned_query,
                            "fields": fields,
                            "default_operator": "AND"
                        }
                    }]

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
            search_term = query
            es_query = {
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase": {field: search_term}} for field in fields
                        ]
                    }
                }
            }

        try:
            response = es.search(index="transcripts", body=es_query, size=1000)
            results = [hit["_source"] for hit in response["hits"]["hits"]]
            return Response({
                "query": query,
                "mode": mode,
                "count": len(results),
                "results": results
            })
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    @swagger_auto_schema(
            method='post',
            request_body=TranscriptNameListInputSerializer,
            responses={200: TestimonySerializer(many=True)}
        )
    @action(detail=False, methods=["post"], url_path="testimony-by-transcripts")
    def get_testimonies_by_transcripts(self, request):
        input_serializer = TranscriptNameListInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        transcript_names = input_serializer.validated_data["transcript_names"]
        transcripts = Transcript.objects.filter(name__in=transcript_names)

        if not transcripts.exists():
            return Response({"error": "No matching transcripts found."}, status=status.HTTP_404_NOT_FOUND)

        testimonies = Testimony.objects.filter(file__in=transcripts).order_by("file_id", "index")

        # ✅ Paginate the queryset
        page = self.paginate_queryset(testimonies)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        # Fallback (unlikely used)
        serializer = self.get_serializer(testimonies, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        method='post',
        request_body=WitnessNameListInputSerializer,
        responses={200: TestimonySerializer(many=True)}
    )
    @action(detail=False, methods=["post"], url_path="testimony-by-witness")
    def get_testimonies_by_witness(self, request):
        input_serializer = WitnessNameListInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        witness_names = input_serializer.validated_data["witness_names"]

        # 🔍 Convert names to first and last name
        name_parts = [name.strip().split(" ", 1) for name in witness_names]
        name_filters = []
        for part in name_parts:
            if len(part) == 2:
                first, last = part
            elif len(part) == 1:
                first, last = part[0], ""
            else:
                continue
            name_filters.append({"first_name": first, "last_name": last})
        # 🔍 Build a Q object to match multiple witnesses
        from django.db.models import Q

        witness_query = Q()
        for name_filter in name_filters:
            witness_query |= Q(**name_filter)

        matched_witnesses = Witness.objects.filter(witness_query)
        if not matched_witnesses.exists():
            return Response({"error": "No matching witnesses found."}, status=status.HTTP_404_NOT_FOUND)

        # ✅ Get related transcripts from the matched witnesses
        transcript_ids = matched_witnesses.values_list("file_id", flat=True).distinct()
        testimonies = Testimony.objects.filter(file_id__in=transcript_ids).order_by("file_id", "index")

        # ✅ Paginate
        page = self.paginate_queryset(testimonies)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(testimonies, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        method='post',
        request_body=CombinedSearchInputSerializer,
        responses={200: TestimonySerializer(many=True)}
        )
    @action(detail=False, methods=["post"], url_path="combined-search")
    def combined_search(self, request):
        serializer = CombinedSearchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        q1 = validated.get("q1", "").strip()
        mode1 = validated.get("mode1", "exact").lower()
        q2 = validated.get("q2", "").strip()
        mode2 = validated.get("mode2", "exact").lower()
        q3 = validated.get("q3", "").strip()
        mode3 = validated.get("mode3", "exact").lower()

        witness_names = validated.get("witness_names", [])
        transcript_names = validated.get("transcript_names", [])
        witness_types = validated.get("witness_types", [])
        sources = validated.get("sources", "all")  # Can be 'all' or a list like ['default', 'farrar']

        bool_query = {
            "must": [],
            "must_not": [],
            "filter": []
        }

        fields = ["question", "answer", "cite", "transcript_name", "witness_name", "type"]
        witness_fields = ["witness_name"]
        transcript_fields = ["transcript_name"]

        def build_query_block(query, mode, target_fields):
            musts = []
            if not query:
                return musts

            if mode == "fuzzy":
                for word in query.split():
                    musts.append({
                        "multi_match": {
                            "query": word,
                            "fields": target_fields,
                            "fuzziness": "AUTO"
                        }
                    })
            elif mode == "boolean":
                if "/s" in query:
                    parts = [part.strip() for part in query.split("/s")]
                    if len(parts) == 2:
                        term1, term2 = parts
                        for field in target_fields:
                            musts.append({
                                "match_phrase": {
                                    field: {
                                        "query": f"{term1} {term2}",
                                        "slop": 5
                                    }
                                }
                            })
                else:
                    not_pattern = r"\bNOT\s+(\w+)"
                    not_terms = re.findall(not_pattern, query, flags=re.IGNORECASE)
                    cleaned_query = re.sub(not_pattern, "", query, flags=re.IGNORECASE).strip()

                    if cleaned_query:
                        musts.append({
                            "query_string": {
                                "query": cleaned_query,
                                "fields": target_fields,
                                "default_operator": "AND"
                            }
                        })

                    for term in not_terms:
                        bool_query["must_not"].append({
                            "multi_match": {
                                "query": term,
                                "fields": target_fields
                            }
                        })
            else:
                musts.append({
                    "simple_query_string": {
                        "query": f'"{query}"',
                        "fields": target_fields,
                        "default_operator": "and"
                    }
                })

            return musts

        # === Filters ===
        if witness_names:
            bool_query["filter"].append({
                "bool": {
                    "should": [
                        {"match_phrase": {"witness_name": name}} for name in witness_names
                    ],
                    "minimum_should_match": 1
                }
            })

        if transcript_names:
            bool_query["filter"].append({
                "bool": {
                    "should": [
                        {"match_phrase": {"transcript_name": name}} for name in transcript_names
                    ],
                    "minimum_should_match": 1
                }
            })

        if witness_types:
            bool_query["filter"].append({
                "bool": {
                    "should": [
                        {"match_phrase": {"type": wt}} for wt in witness_types
                    ],
                    "minimum_should_match": 1
                }
            })

        # ✅ Filter by database source
        if isinstance(sources, list) and sources:
            bool_query["filter"].append({
                "bool": {
                    "should": [
                        {"term": {"source": s}} for s in sources
                    ],
                    "minimum_should_match": 1
                }
            })

        # === q1, q2, q3 search ===
        bool_query["must"].extend(build_query_block(q1, mode1, fields))
        bool_query["must"].extend(build_query_block(q2, mode2, witness_fields))
        bool_query["must"].extend(build_query_block(q3, mode3, transcript_fields))

        es_query = {
            "query": {
                "bool": bool_query
            },
            "sort": [
            {"created_at": "asc"}  # or "desc"
        ]
        }

        try:
            response = es.search(index="transcripts", body=es_query, size=10000, )
            results = [hit["_source"] for hit in response["hits"]["hits"]]
            return Response({
                "query1": q1,
                "query2": q2,
                "query3": q3,
                "mode1": mode1,
                "mode2": mode2,
                "mode3": mode3,
                "sources": sources,
                "count": len(results),
                "results": results
            })
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class WitnessViewSet(viewsets.ViewSet):
    def list(self, request):
        witnesses = Witness.objects.all()
        serializer = WitnessSerializer(witnesses, many=True)

        # Get counts grouped by WitnessType
        type_counts = Witness.objects.values("type__type").annotate(count=Count("id"))

        return Response({
            "witnesses": serializer.data,
            "count": len(serializer.data),
            "type_counts": type_counts
        })
    # def create(self, request):
    #     # Expecting JSON body: { "sources": ["default", "farrar"] } or "all"
    #     sources_param = request.data.get('sources', 'all')

    #     if sources_param == 'all':
    #         selected_sources = ['default', 'farrar']
    #     elif isinstance(sources_param, list):
    #         selected_sources = [src for src in sources_param if src in ['default', 'farrar']]
    #     else:
    #         return Response({"error": "Invalid 'sources' format"}, status=400)

    #     all_witnesses = []

    #     if 'default' in selected_sources:
    #         pg_witnesses = Witness.objects.using('default').all()
    #         all_witnesses.extend(pg_witnesses)

    #     if 'farrar' in selected_sources:
    #         mysql_witnesses = Witness.objects.using('farrar').all()
    #         all_witnesses.extend(mysql_witnesses)

    #     serializer = WitnessSerializer(all_witnesses, many=True)
    #     return Response({
    #         "source": selected_sources,
    #         "witnesses": serializer.data,
    #         "count": len(serializer.data)
    #     })


    # ✅ GET /witness/save-witnesses/ → get names from SharePoint only
    @action(detail=False, methods=["post"], url_path="save-witnesses")
    def save_witnesses(self, request):
            results = fetch_witness_names_and_transcripts()
            # Fetch defaults
            witness_type = WitnessType.objects.first()

            alignment = WitnessAlignment.objects.first()

            default_user = User.objects.first()
            default_project = Project.objects.first()
            # print("resultssssss",results)
            created_t = 0
            created_w = 0
            for item in results:
                fullname = item.get("witness_name")
                transcript_name = item.get("transcript_name")
                transcript_date = item.get("transcript_date")
                # transcript_date_obj = datetime.strptime(transcript_date, "%m-%d-%Y").date()
                transcript_date_obj = parse_date(transcript_date).date()


                if not (fullname and transcript_name and transcript_date):
                    print("not found", transcript_name)
                    continue
                if not Transcript.objects.filter(
                    name=transcript_name,
                    transcript_date=transcript_date_obj,
                    created_by=default_user,
                    project=default_project
                ).exists():
                    Transcript.objects.create(
                        name=transcript_name,
                        transcript_date=transcript_date_obj,
                        created_by=default_user,
                        project=default_project
                    )
                    created_t += 1
                transcript = Transcript.objects.filter(name=transcript_name).first()
                if not transcript:
                    print("Transcript not found for:", transcript_name)

                # # Avoid duplicates
                if not Witness.objects.filter(
                    file=transcript,
                    fullname=fullname,
                    alignment=alignment,
                    type=witness_type
                ).exists():
                    Witness.objects.create(
                        file=transcript,
                        fullname=fullname,
                        alignment=alignment,
                        type=witness_type
                    )
                    created_w += 1
                                # Avoid duplicates


            return Response({
                "status": "success",
                "inserted_transcripts": created_t,
                "inserted_witnesses": created_w,
                "total_fetched": len(results)
            })

class WitnessTypeViewSet(viewsets.ModelViewSet):
    http_method_names = ["get"]
    queryset = WitnessType.objects.all()
    serializer_class = WitnessTypeSerializer
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "source": "postgres",
            "witnesses": serializer.data,
            "count": len(serializer.data)
        })

class WitnessAlignmentViewSet(viewsets.ModelViewSet):
    http_method_names = ["get"]
    queryset = WitnessAlignment.objects.all()
    serializer_class = WitnessAlignmentSerializer
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "source": "postgres",
            "witnesses": serializer.data,
            "count": len(serializer.data)
        })
    @action(detail=False, methods=["get"], url_path="save-taxonomy")
    def save_taxonomy(self, request):
        try:
            data = fetch_taxonomy_from_sharepoint()
            witness_list = data.get("Witness", [])

            for item in witness_list:
                full_name = item.get("Name")
                types = item.get("Types", [])

                if not full_name or not types:
                    print(f"Skipping — name or types missing.")
                    continue

                witness_type_raw = types[0].get("Type")
                if not witness_type_raw or not isinstance(witness_type_raw, str):
                    print(f"Skipping {full_name} — invalid type.")
                    continue

                witness_type_name = witness_type_raw.strip()
                if not witness_type_name:
                    print(f"Skipping {full_name} — empty type.")
                    continue

                # Get or create witness type
                witness_type_obj, _ = WitnessType.objects.get_or_create(type=witness_type_name)

                try:
                    last_name, first_name = [x.strip() for x in full_name.split(",")]
                except Exception:
                    print(f"Skipping invalid name format: {full_name}")
                    continue

                try:
                    witness = Witness.objects.get(first_name=last_name+",", last_name=first_name)
                    witness.type_id = witness_type_obj.id
                    witness.save()
                    print(f"✅ Updated: {first_name} {last_name} with type '{witness_type_name}' (ID {witness_type_obj.id})")
                except Witness.DoesNotExist:
                    print(f"❌ Witness not found: {first_name} {last_name}")
                except Exception as e:
                    print(f"⚠️ Error updating {full_name}: {e}")


            return Response({"message": "Witness types updated successfully"}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)





class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer

    # ✅ Default: GET /witness/ → fetch from PostgreSQL DB
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "source": "postgres",
            "comments": serializer.data,
            "count": len(serializer.data)
        })
    def create(self, request, *args, **kwargs):
        # Save the comment in PostgreSQL
        response = super().create(request, *args, **kwargs)
        INDEX_NAME = "transcripts"
        # Extract data from saved comment
        testimony_id = response.data.get("testimony")
        testimony = Testimony.objects.get(id=testimony_id)
        content = response.data.get("content")

        userData = response.data.get("user")
        user = User.objects.filter(id=userData).first()

        commenter_email = user.email
        commenter_name = user.name

        # Create a comment
        comment = Comment.objects.create(
            testimony=testimony,
            user=user,
            content=content
        )

        if testimony_id:
            es_id = f"default_{testimony_id}"  # Matches your ES indexing format
            try:
                # Get current ES document
                doc = es.get(index=INDEX_NAME, id=es_id)["_source"]

                # If commenter_emails doesn't exist, create it
                existing_commenters = doc.get("commenter_emails", [])
                print(existing_commenters)
                # Avoid duplicates
                if not any(c["email"] == commenter_email for c in existing_commenters):
                    existing_commenters.append({
                        "name": commenter_name,
                        "email": commenter_email
                    })

                    # Update ES document
                    es.update(
                        index=INDEX_NAME,
                        id=es_id,
                        body={"doc": {"commenter_emails": existing_commenters}}
                    )
                    print(f"✅ Updated commenter_emails for {es_id}")

            except Exception as e:
                print(f"❌ Error updating ES doc {es_id}: {str(e)}")

        return response

    def destroy(self, request, *args, **kwargs):
        INDEX_NAME = "transcripts"
        comment = self.get_object()

        # Get details before deleting
        testimony_id = comment.testimony.id
        commenter_email = comment.user.email

        # 1️⃣ Delete from PostgreSQL
        comment.delete()

        # 2️⃣ Check if user still has comments on this testimony
        still_has_comments = Comment.objects.filter(
            testimony_id=testimony_id,
            user__email=commenter_email
        ).exists()

        # 3️⃣ Update Elasticsearch only if user has no other comments
        if not still_has_comments:
            es_id = f"default_{testimony_id}"
            try:
                doc = es.get(index=INDEX_NAME, id=es_id)["_source"]
                existing_commenters = doc.get("commenter_emails", [])

                updated_commenters = [
                    c for c in existing_commenters 
                    if c.get("email") != commenter_email
                ]

                if updated_commenters != existing_commenters:
                    es.update(
                        index=INDEX_NAME,
                        id=es_id,
                        body={"doc": {"commenter_emails": updated_commenters}}
                    )
                    print(f"🗑 Removed {commenter_email} from ES for {es_id}")
            except Exception as e:
                print(f"❌ Error updating ES doc {es_id}: {str(e)}")

        return Response({"message": "✅ Comment deleted"}, status=status.HTTP_204_NO_CONTENT)
    # ✅ New: GET /comments/by-testimony/<id>/
    @swagger_auto_schema(operation_description="Get all comments by testimony ID")
    @action(detail=False, methods=["get"], url_path="by-testimony/(?P<testimony_id>[^/.]+)")
    def by_testimony(self, request, testimony_id=None):
        comments = Comment.objects.filter(testimony_id=testimony_id)
        serializer = self.get_serializer(comments, many=True)
        return Response({
            "testimony_id": testimony_id,
            "count": len(serializer.data),
            "comments": serializer.data
        })

# class CommentViewSet(viewsets.ModelViewSet):
#     queryset = Comment.objects.all()
#     serializer_class = CommentSerializer

#     # ✅ Default: GET /witness/ → fetch from PostgreSQL DB
#     def list(self, request, *args, **kwargs):
#         queryset = self.get_queryset()
#         serializer = self.get_serializer(queryset, many=True)
#         return Response({
#             "source": "postgres",
#             "comments": serializer.data,
#             "count": len(serializer.data)
#         })
    

    
    
class HighlightsViewSet(viewsets.ModelViewSet):
    queryset = Highlights.objects.all()
    serializer_class = HighlightsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    @action(detail=False, methods=["post"], url_path="msal-sync")
    def msal_sync(self, request):
        email = request.data.get("email")
        name = request.data.get("name", "")
        msal_id = request.data.get("msal_id")

        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        user, created = User.objects.get_or_create(
            email=email,
            defaults={"name": name, "msal_id": msal_id}
        )

        if not created:
            user.name = name
            user.msal_id = msal_id
            user.save()

        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)