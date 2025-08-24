from django.contrib import admin
from .models import Project, Transcript, ExpertType, Jurisdiction, ProjectUser, WitnessType, WitnessAlignment, Witness, WitnessFiles, Testimony, Attorney
 
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'created_by']  # customize as needed

@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ['id', 'name','transcript_date', 'created_by', 'project', 'file']

@admin.register(Attorney)
class AttorneyAdmin(admin.ModelAdmin):
    list_display = ['id', 'name','type', 'file', 'law_firm']

@admin.register(Jurisdiction)
class JurisdictionAdmin(admin.ModelAdmin):
    list_display = ['id', 'name','project']
    
@admin.register(ProjectUser)
class ProjectUserAdmin(admin.ModelAdmin):
    list_display = ['id', 'project', 'user']

@admin.register(WitnessType)
class WitnessTypeAdmin(admin.ModelAdmin):
    list_display = ['id', 'type']

@admin.register(ExpertType)
class ExpertTypeAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'file', 'witness']

@admin.register(WitnessAlignment)
class WitnessAlignmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'alignment']

@admin.register(Witness)
class WitnessAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'fullname', 'alignment', 'file']

@admin.register(WitnessFiles)
class WitnessFilesAdmin(admin.ModelAdmin):
    list_display = ['id', 'witness', 'file']

@admin.register(Testimony)
class TestimonyAdmin(admin.ModelAdmin):
    list_display = ['id', 'question', 'answer', 'index', 'cite', 'file']