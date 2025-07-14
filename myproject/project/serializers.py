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
)


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = "__all__"


class TranscriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = "__all__"


class ProjectUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectUser
        fields = "__all__"


class WitnessTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = WitnessType
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


class TestimonySerializer(serializers.ModelSerializer):
    transcript_name = serializers.CharField(source="file.name", read_only=True)
    commenter_emails = serializers.SerializerMethodField()

    class Meta:
        model = Testimony
        fields = "__all__"
        extra_fields = ["transcript_name", "commenter_emails"]

    def get_commenter_emails(self, obj):
        comments = obj.comments.all()  # assuming related_name="comments"
        if not comments.exists():
            return None  # or [] if you want empty list instead of null
        return list(set(comment.user.email for comment in comments))


class TranscriptNameInputSerializer(serializers.Serializer):
    transcript_name = serializers.CharField()


class TranscriptNameListInputSerializer(serializers.Serializer):
    transcript_names = serializers.ListField(
        child=serializers.CharField(), allow_empty=False
    )


class WitnessNameListInputSerializer(serializers.Serializer):
    witness_names = serializers.ListField(
        child=serializers.CharField(), allow_empty=False
    )


class CombinedSearchInputSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True)
    mode = serializers.ChoiceField(
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

class CommentSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "user", "user_email", "testimony", "content", "created_at"]
        read_only_fields = ["created_at"]


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
