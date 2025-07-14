from django.db import models

class TranscriptEntry(models.Model):
    question = models.TextField(blank=True, null=True)
    answer = models.TextField(blank=True, null=True)
    cite = models.TextField(blank=True, null=True)  # renamed from 'cite'
    filename = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.filename}: {self.question[:30]}"
    
class WitnessEntry(models.Model):
    witness_name = models.CharField(max_length=255)
    filename = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.filename} - {self.witness_name}"
    
class FilenameEntry(models.Model):
    filename = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.filename} - {self.filename}"