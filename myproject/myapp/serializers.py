from rest_framework import serializers
from .models import TranscriptEntry, WitnessEntry, FilenameEntry

class TranscriptEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = TranscriptEntry
        fields = '__all__'
class WitnessEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = WitnessEntry
        fields = '__all__'

class FilenameEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = FilenameEntry
        fields = '__all__'