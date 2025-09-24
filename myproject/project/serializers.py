# serializers.py
from rest_framework import serializers
from .models import (
    Project,
    Highlights,
    Comment,
    Transcript,
    ProjectUser,
    WitnessType,
    WitnessAlignment,
    Witness,
    WitnessFiles,
    Testimony,
    Attorney,
    Jurisdiction,
    ExpertType
)

from user.serializers import UserSerializer


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = "__all__"


class TranscriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = "__all__"

class AttorneySerializer(serializers.ModelSerializer):
    class Meta:
        model = Attorney
        fields = "__all__"

class ProjectUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectUser
        fields = "__all__"

class JurisdictionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Jurisdiction
        fields = "__all__"

class WitnessTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = WitnessType
        fields = "__all__"

class ExpertTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpertType
        fields = "__all__"

class WitnessAlignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = WitnessAlignment
        fields = "__all__"


class WitnessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Witness
        fields = "__all__"


class WitnessFilesSerializer(serializers.ModelSerializer):
    class Meta:
        model = WitnessFiles
        fields = "__all__"

class CommentSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.EmailField(source="user.name", read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "user", "email", "name", "testimony", "content", "created_at"]
        read_only_fields = ["created_at"]


class TestimonySerializer(serializers.ModelSerializer):
    transcript_name = serializers.CharField(source="file.name", read_only=True)
    commenter_emails = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)  # 👈 adds comments array

    class Meta:
        model = Testimony
        fields = "__all__"
        extra_fields = ["transcript_name", "commenter_emails", "comments"]

    def get_commenter_emails(self, obj):
        comments = obj.comments.select_related("user").all()
        users = {comment.user for comment in comments if comment.user}  # deduplicate
        serialized_users = UserSerializer(users, many=True).data
        return serialized_users if serialized_users else None

class TranscriptNameInputSerializer(serializers.Serializer):
    transcript_name = serializers.CharField()


class TranscriptNameListInputSerializer(serializers.Serializer):
    transcript_names = serializers.ListField(
        child=serializers.CharField(), allow_empty=False
    )
class TranscriptFuzzySerializer(serializers.Serializer):
    transcript_name = serializers.CharField(allow_blank=True, required=False)

class WitnessFuzzySerializer(serializers.Serializer):
    witness_name = serializers.CharField(allow_blank=True, required=False)

class WitnessNameListInputSerializer(serializers.Serializer):
    witness_names = serializers.ListField(
        child=serializers.CharField(), allow_empty=False
    )


class CombinedSearchInputSerializer(serializers.Serializer):
    q1 = serializers.CharField(required=False, allow_blank=True)
    mode1 = serializers.ChoiceField(
        choices=["fuzzy", "boolean", "exact"], required=False, default="exact"
    )
    q2 = serializers.CharField(required=False, allow_blank=True)
    mode2 = serializers.ChoiceField(
        choices=["fuzzy", "boolean", "exact"], required=False, default="exact"
    )
    q3 = serializers.CharField(required=False, allow_blank=True)
    mode3 = serializers.ChoiceField(
        choices=["fuzzy", "boolean", "exact"], required=False, default="exact"
    )
    witness_names = serializers.ListField(
        child=serializers.CharField(allow_blank=True),  # ✅ explicitly allow blank
        required=False,
        allow_empty=True,
    )

    transcript_names = serializers.ListField(
        child=serializers.CharField(allow_blank=True),  # ✅ explicitly allow blank
        required=False,
        allow_empty=True,
    )
    witness_types = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )

    witness_alignments = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True
    )

    # ✅ Pagination support
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=1000)

class CombinedTranscriptSearchSerializer(serializers.Serializer):
    q1 = serializers.CharField(required=False, allow_blank=True)
    mode1 = serializers.ChoiceField(
        choices=["fuzzy", "boolean", "exact"], required=False, default="exact"
    )
    q2 = serializers.CharField(required=False, allow_blank=True)
    mode2 = serializers.ChoiceField(
        choices=["fuzzy", "boolean", "exact"], required=False, default="exact"
    )
    q3 = serializers.CharField(required=False, allow_blank=True)
    mode3 = serializers.ChoiceField(
        choices=["fuzzy", "boolean", "exact"], required=False, default="exact"
    )
    witness_names = serializers.ListField(
        child=serializers.CharField(allow_blank=True),  # ✅ explicitly allow blank
        required=False,
        allow_empty=True,
    )

    transcript_names = serializers.ListField(
        child=serializers.CharField(allow_blank=True),  # ✅ explicitly allow blank
        required=False,
        allow_empty=True,
    )
    witness_types = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )

    witness_alignments = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True
    )

    # ✅ Pagination support
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=1000)

class HighlightsSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    testimony_id = serializers.IntegerField(source="testimony.id", read_only=True)

    class Meta:
        model = Highlights
        fields = [
            "id",
            "testimony",
            "testimony_id",
            "user",
            "user_email",
            "highlight",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user_email",
            "testimony_id",
            "created_at",
            "updated_at",
        ]
