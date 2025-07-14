from django.contrib import admin
from .models import Project, Transcript, ProjectUser, WitnessType, WitnessAlignment, Witness, WitnessFiles, Testimony
 
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'created_by']  # customize as needed

@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ['id', 'name','transcript_date', 'created_by', 'project', 'file']

@admin.register(ProjectUser)
class ProjectUserAdmin(admin.ModelAdmin):
    list_display = ['id', 'project', 'user']

@admin.register(WitnessType)
class WitnessTypeAdmin(admin.ModelAdmin):
    list_display = ['id', 'type']

@admin.register(WitnessAlignment)
class WitnessAlignmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'alignment']

@admin.register(Witness)
class WitnessAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'first_name', 'last_name', 'alignment', 'file']

@admin.register(WitnessFiles)
class WitnessFilesAdmin(admin.ModelAdmin):
    list_display = ['id', 'witness', 'file']

@admin.register(Testimony)
class TestimonyAdmin(admin.ModelAdmin):
    list_display = ['id', 'question', 'answer', 'index', 'cite', 'file']