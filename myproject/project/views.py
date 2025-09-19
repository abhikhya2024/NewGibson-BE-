from rest_framework import viewsets
from .models import Project, Comment, Jurisdiction, ExpertType, Attorney,Highlights, Testimony, Transcript, Witness, WitnessType, WitnessAlignment, WitnessFiles
from .serializers import ProjectSerializer,CommentSerializer, ExpertTypeSerializer, JurisdictionSerializer, AttorneySerializer, TranscriptFuzzySerializer, WitnessFuzzySerializer, HighlightsSerializer, TestimonySerializer, CombinedSearchInputSerializer, TranscriptSerializer,TranscriptNameListInputSerializer, WitnessNameListInputSerializer, WitnessSerializer, WitnessAlignmentSerializer, WitnessTypeSerializer
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.decorators import action
from .sharepoint_utils import fetch_from_sharepoint, get_dive_id, get_access_token, fetch_attorney, fetch_jurisdictions, fetch_witness_names_and_transcripts, fetch_json_files_from_sharepoint, fetch_taxonomy_from_sharepoint
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
import unicodedata
from collections import defaultdict
from .tasks import save_testimony_task, index_task
import logging
from elasticsearch.helpers import bulk
import requests

logger = logging.getLogger("logging_handler")  # 👈 custom logger name

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

class JurisdictionViewSet(viewsets.ModelViewSet):
    queryset = Jurisdiction.objects.all()
    serializer_class = JurisdictionSerializer
    parser_classes = [MultiPartParser]  # 👈 required for form-data upload

    def list(self, request, *args, **kwargs):
        jurisdiction = self.get_queryset()

        # Serialize full list
        serializer = self.get_serializer(jurisdiction, many=True)

        # Group by jurisdiction name/field and count
        jurisdiction_counts = (
            jurisdiction
            .values("name")   # 👈 replace with the field that identifies jurisdiction
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        return Response({
            "count": jurisdiction.count(),
            "jurisdiction": serializer.data,
            "jurisdiction_counts": jurisdiction_counts
        })
    @swagger_auto_schema(
        method='get',
        responses={200: JurisdictionSerializer(many=True)}
    )
    @action(detail=False, methods=["get"], url_path="save-jurisdictions")
    def save_jurisdictions(self, request):
        logger.info("✅ Log test from views.py")

        try:
            # Annotate each transcript with testimony count
            results = fetch_jurisdictions()
            
            created = 0
            for item in results:
                jurisdiction = item.get("jurisdiction")

                if not jurisdiction:
                    continue

                # Avoid duplicates
                if not Jurisdiction.objects.filter(name=jurisdiction).exists():
                    Jurisdiction.objects.create(name=jurisdiction)
                    created += 1

            return Response({
                "status": "success",
                "inserted": created,
                "total_fetched": len(results)
            })

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

 


from itertools import chain
from django.db.models import Count
from rest_framework.response import Response

class TranscriptViewSet(viewsets.ModelViewSet):
    queryset = Transcript.objects.all()
    serializer_class = TranscriptSerializer
    parser_classes = [MultiPartParser]

    def list(self, request, *args, **kwargs):
        # ---- Step 1: Get site_id and drive_id

        
        # ---- Step 5: Fetch transcripts from default DB
        transcripts_default = Transcript.objects.using('default').all()

        # Serialize data
        serializer = self.get_serializer(transcripts_default, many=True)

        # Unique case count
        unique_cases_default = Transcript.objects.using('default').values('case_name').distinct()
        unique_case_count = len(unique_cases_default)

        # Deposition count per case
        case_counts_default = (
            Transcript.objects.using('default')
            .values("case_name")
            .annotate(transcript_count=Count("id"))
            .order_by("-transcript_count")
        )
        case_counts = list(case_counts_default)
        # ---- Step 6: Return combined response
        return Response({
            "count": transcripts_default.count(),
            "transcripts": serializer.data,
            "unique_cases": unique_case_count,
            "depo_per_case": case_counts,
            "site_id": site_id,   # 👈 Graph API response added here
            "drive_id": drive_id
        })


    @action(detail=False, methods=["post"], url_path="create-index")
    def create_index(self, request):
        INDEX_NAME="testimonies"
        try:
            # Step 1: Delete old index if exists
            if es.indices.exists(index=INDEX_NAME):
                es.indices.delete(index=INDEX_NAME)
                logger.info(f"🗑 Deleted old index: '{INDEX_NAME}'")

            # Step 2: Create new index
            mapping = {
                "mappings": {
                    "properties": {
                        "id": {"type": "integer"},
                        "question": {"type": "text"},
                        "answer": {"type": "text"},
                        "cite": {"type": "text"},
                        "transcript_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                        "witness_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                        "type": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                        "alignment": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                        "source": {"type": "keyword"},
                        "commenter_emails": {
                            "type": "nested",
                            "properties": {"name": {"type": "text"}, "email": {"type": "keyword"}},
                        },
                        "created_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
                                                "transcript_date": {
                            "type": "date",
                        }
                    }
                }
            }
            es.indices.create(index=INDEX_NAME, body=mapping)
            logger.info(f"✅ Created new index: '{INDEX_NAME}'")

            # Step 3: Trigger background task
            task = index_task.delay(INDEX_NAME)

            return Response(
                {
                    "status": "processing",
                    "task_id": task.id,
                    "message": f"Indexing started for '{INDEX_NAME}' in background.",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        except Exception as e:
            logger.error(f"❌ Error in create_index: {str(e)}")
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
                case_name = item.get("case_name")
                transcript_date_obj = datetime.strptime(transcript_date, "%m-%d-%Y").date()

                if not (transcript_name and transcript_date):
                    continue

                # Avoid duplicates
                if not Transcript.objects.filter(
                    name=transcript_name,
                    transcript_date=transcript_date_obj,
                    created_by=default_user,
                    project=default_project,
                    case_name=case_name
                ).exists():
                    Transcript.objects.create(
                        name=transcript_name,
                        transcript_date=transcript_date_obj,
                        created_by=default_user,
                        project=default_project,
                        case_name=case_name
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

class AttorneyViewSet(viewsets.ModelViewSet):
    queryset = Attorney.objects.all()
    serializer_class = AttorneySerializer
    parser_classes = [MultiPartParser]

    def list(self, request, *args, **kwargs):
        attorneys = self.get_queryset()
        serializer = self.get_serializer(attorneys, many=True)

        # Group by law_firm and count distinct files (Transcript instances)
        law_firm_file_counts = (
            attorneys
            .values('law_firm')
            .annotate(file_count=Count('file', distinct=True))
            .order_by('law_firm')
        )

        return Response({
            "count": attorneys.count(),
            "attorneys": serializer.data,
            "file_counts_by_law_firm": list(law_firm_file_counts),
        })
    @action(detail=False, methods=["get"], url_path="save-attorney")
    def get(self, request):
        results = fetch_attorney()
        created = 0

        for item in results:
            if not item:  # skip None entries just in case
                continue

            atty_type = item.get("type")
            name = item.get("name")
            law_firm = item.get("law_firm")
            transcript_name = item.get("transcript_name")

            # Ensure transcript exists
            transcript = Transcript.objects.filter(name__icontains=transcript_name).first()
            if not transcript:
                print("Transcript not found for:", transcript_name)
                continue  # skip if transcript missing

            # Ensure we have a valid name
            if not name:
                print("Attorney name missing for transcript:", transcript_name)
                continue

            # Avoid duplicates
            if not Attorney.objects.filter(
                name=name,
                type=atty_type,
                law_firm=law_firm,
                file=transcript
            ).exists():
                Attorney.objects.create(
                    name=name,
                    type=atty_type,
                    law_firm=law_firm,
                    file=transcript
                )
                created += 1

        return Response({
            "status": "success",
            "inserted": created,
            "total_fetched": len([i for i in results if i])  # count only valid items
        })


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

    @swagger_auto_schema(
        method='get',
        operation_description="Get testimony count for each transcript",
        responses={200: 'A list of transcripts with testimony count'}
    )
    @action(detail=False, methods=["get"], url_path="testimony-cnt-by-transcripts")
    def testimony_count_by_transcript(self, request):
        data = (
            Transcript.objects
            .annotate(testimony_count=Count('testimony_data'))
            .values('name', 'testimony_count')
        )
        return Response(list(data), status=status.HTTP_200_OK)
    @action(detail=False, methods=["get"], url_path="depositions-per-case")
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
        task = save_testimony_task.delay()  # 🔥 async call
        return Response({
            "status": "processing",
            "task_id": task.id
        })
        # try:
        #     results = fetch_json_files_from_sharepoint()

        #     qa_objects = []
        #     skipped = 0

        #     for item in results:
        #         item.pop("id", None)
        #         txt_filename = item.get("filename")

        #         transcript = Transcript.objects.filter(name=txt_filename).first()
        #         if not transcript:
        #             print(f"❌ Skipping again: No transcript found for {txt_filename}")
        #             skipped += 1
        #             continue

        #         question = item.get("question")
        #         answer = item.get("answer")
        #         cite = item.get("cite")
        #         index = item.get("index")

        #         if not Testimony.objects.filter(
        #             question=question,
        #             answer=answer,
        #             cite=cite,
        #             index=index,
        #             file=transcript
        #         ).exists():
        #             qa_objects.append(Testimony(
        #                 question=question,
        #                 answer=answer,
        #                 cite=cite,
        #                 index=index,
        #                 file=transcript
        #             ))
        #             print("inserted QA pair")

        #     Testimony.objects.bulk_create(qa_objects, batch_size=1000)

        #     return Response({
        #         "status": "success",
        #         "inserted": len(qa_objects),
        #         "skipped_due_to_missing_transcript": skipped,
        #         "total_fetched": len(results)
        #     })

        # except Exception as e:
        #     return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        sources = validated.get("sources", "all")  # Can be 'all' or a list like ['default', 'cummings']

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
            response = es.search(index="testimonies", body=es_query, size=10000, )
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
        # Serialize all witnesses
        witnesses = Witness.objects.all()
        serializer = WitnessSerializer(witnesses, many=True)

        # Fetch witnesses along with their transcripts
        witnesses_with_files = Witness.objects.select_related('file').all()

        # Prepare list of dicts: one row per witness-transcript pair
        transcripts_by_witness = []
        for w in witnesses_with_files:
            if w.fullname:
                transcripts_by_witness.append({
                    "witness": w.fullname,
                    "transcript": w.file.name if w.file else None
                })

        # Counts grouped by WitnessType (excluding null types)
        type_counts = (
            Witness.objects
            .exclude(type__isnull=True)
            .values("type__type")
            .annotate(count=Count("id"))
        )

        # Counts grouped by Alignment (excluding null alignments)
        alignment_counts = (
            Witness.objects
            .exclude(alignment__isnull=True)
            .values("alignment__alignment")
            .annotate(count=Count("id"))
        )

        return Response({
            "witnesses": serializer.data,
            "count": len(serializer.data),
            "type_counts": type_counts,
            "alignment_counts": alignment_counts,
            "transcripts_by_witness": transcripts_by_witness
        })
    
    @action(detail=False, methods=["get"], url_path="save-taxonomy")
    def save_taxonomy(self, request):
        try:
            result = fetch_taxonomy_from_sharepoint()

            created_a = 0
            created_t = 0
            updated_w = 0
            created_e = 0

            def normalize_name(name):
                return unicodedata.normalize("NFKC", name).strip()

            for item in result:
                alignment = item.get("alignment")
                witness_name = item.get("witness_name")
                witness_type = item.get("witness_type")
                expert_type = item.get("expert_type")
                transcript_name = item.get("transcript_name")
                print("transcript", transcript_name)

                # ⚠️ Ensure all required fields exist
                if not witness_name or not alignment or not witness_type and expert_type:
                    print(f"⚠️ Skipping witness: {witness_name} (missing alignment/type)")
                    continue

                # ✅ Ensure alignment exists
                alignment_obj, created = WitnessAlignment.objects.get_or_create(
                    alignment=alignment.strip()
                )
                if created:
                    created_a += 1

                # ✅ Ensure type exists
                type_obj, created = WitnessType.objects.get_or_create(
                    type=witness_type.strip()
                )
                if created:
                    created_t += 1

                # ✅ Normalize witness name and find all matching witnesses

                # Avoid duplicates
                witness = Witness.objects.filter(fullname=witness_name).first()
                transcript = Transcript.objects.filter(name=transcript_name).first()
                if witness and transcript:
                    ExpertType.objects.create(type=expert_type, witness=witness,file=transcript )
                    created_e += 1
                normalized_name = normalize_name(witness_name)
                witnesses = Witness.objects.filter(fullname__iexact=normalized_name)

                if witnesses.exists():
                    for witness in witnesses:
                        updated = False
                        if witness.alignment != alignment_obj:
                            witness.alignment = alignment_obj
                            updated = True
                        if witness.type != type_obj:
                            witness.type = type_obj
                            updated = True

                        if updated:
                            witness.save()
                            updated_w += 1
                else:
                    print(f"⚠️ Witness '{witness_name}' not found in DB")

            # ✅ Return after processing all items
            return Response({
                "status": "success",
                "inserted_alignments": created_a,
                "inserted_types": created_t,
                "total_fetched": len(result),
                "witness_updated": updated_w,
                "expert_type_inserted": created_e
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    @action(detail=False, methods=["post"], url_path="save-witnesses")
    def save_witnesses(self, request):
            results = fetch_witness_names_and_transcripts()
            # Fetch defaults
            # witness_type = WitnessType.objects.first()

            # alignment = WitnessAlignment.objects.first()

            # default_user = User.objects.first()
            # default_project = Project.objects.first()
            # # print("resultssssss",results)
            # created_t = 0
            # created_w = 0
            # for item in results:
            #     fullname = item.get("witness_name")
            #     transcript_name = item.get("transcript_name")
            #     transcript_date = item.get("transcript_date")
            #     case_name = item.get("case_name")
            #     # transcript_date_obj = datetime.strptime(transcript_date, "%m-%d-%Y").date()
            #     transcript_date_obj = parse_date(transcript_date).date()


            #     if not (fullname and transcript_name and transcript_date):
            #         print("not found", transcript_name)
            #         continue
            #     if not Transcript.objects.filter(
            #         name=transcript_name,
            #         transcript_date=transcript_date_obj,
            #         created_by=default_user,
            #         project=default_project,
            #         case_name=case_name
            #     ).exists():
            #         Transcript.objects.create(
            #             name=transcript_name,
            #             transcript_date=transcript_date_obj,
            #             created_by=default_user,
            #             project=default_project,
            #             case_name=case_name
            #         )
            #         created_t += 1
            #     transcript = Transcript.objects.filter(name=transcript_name).first()
            #     if not transcript:
            #         print("Transcript not found for:", transcript_name)

            #     # # Avoid duplicates
            #     if not Witness.objects.filter(
            #                 file=transcript,
            #                 fullname=fullname,
            #                 alignment=alignment,
            #                 type=witness_type
            #             ).exists():
            #                 Witness.objects.create(
            #                     file=transcript,
            #                     fullname=fullname,
            #                     alignment=alignment,
            #                     type=witness_type
            #                 )
            #     created_w += 1
            #                     # Avoid duplicates



            return Response({
                "status": "success",
                "results": results
                # "inserted_transcripts": created_t,
                # "inserted_witnesses": created_w,
                # "total_fetched": len(results)
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
    
class ExpertTypeViewSet(viewsets.ModelViewSet):
    queryset = ExpertType.objects.all()
    serializer_class = ExpertTypeSerializer

    def list(self, request, *args, **kwargs):
        # Get all experts
        experts = self.get_queryset()
        serializer = self.get_serializer(experts, many=True)

        # Count by type (exclude null types)
        type_counts = ExpertType.objects \
            .exclude(type__isnull=True) \
            .values("type") \
            .annotate(count=Count("id")) \
            .order_by("type")

        return Response({
            "experts": serializer.data,
            "total_experts": experts.count(),
            "type_counts": type_counts
        }, status=status.HTTP_200_OK)
    
