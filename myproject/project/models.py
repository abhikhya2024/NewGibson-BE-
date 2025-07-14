from django.db import models
from base.models import TimestampedModel
from user.models import User
from django.conf import settings
# Create your models here.

class Project(TimestampedModel):
    """
    An abstract base class model that provides self-updating 'created_at' and 'updated_at' fields.
    """
    name = models.CharField(max_length=500)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    def __str__(self):
        return self.name
    
class Transcript(TimestampedModel):
    """
    An abstract base class model that provides self-updating 'created_at' and 'updated_at' fields.
    """
    name = models.CharField(max_length=500)
    transcript_date = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    file= models.FileField(upload_to="transcripts", null=True)
    def __str__(self):
        return self.file.name
class ProjectUser(TimestampedModel):
    """
    An abstract base class model that provides self-updating 'created_at' and 'updated_at' fields.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)

class WitnessType(TimestampedModel):
    """
    An abstract base class model that provides self-updating 'created_at' and 'updated_at' fields.
    """
    type = models.CharField(max_length=50)
    def __str__(self):
        return self.type
    
class WitnessAlignment(TimestampedModel):
    """
    An abstract base class model that provides self-updating 'created_at' and 'updated_at' fields.
    """
    alignment = models.CharField(max_length=50)
    def __str__(self):
        return self.alignment
class Witness(TimestampedModel):
    """
    An abstract base class model that provides self-updating 'created_at' and 'updated_at' fields.
    """
    type = models.ForeignKey(WitnessType, on_delete=models.CASCADE)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    alignment = models.ForeignKey(WitnessAlignment, on_delete=models.CASCADE)
    file = models.ForeignKey(Transcript, on_delete=models.CASCADE)

 

class WitnessFiles(TimestampedModel):
    """
    An abstract base class model that provides self-updating 'created_at' and 'updated_at' fields.
    """
    witness = models.ForeignKey(Witness, on_delete=models.CASCADE)
    file = models.ForeignKey(Transcript, on_delete=models.CASCADE)



class Testimony(TimestampedModel):
    """
    An abstract base class model that provides self-updating 'created_at' and 'updated_at' fields.
    """
    question = models.TextField()
    answer = models.TextField()
    index = models.FloatField()
    cite = models.CharField(max_length=50)
    file = models.ForeignKey(Transcript, on_delete=models.CASCADE)

# class Comments(TimestampedModel):
#     """
#     An abstract base class model that provides self-updating 'created_at' and 'updated_at' fields.
#     """
#     email = models.TextField()
#     testimony = models.ForeignKey(Testimony, on_delete=models.CASCADE)
#     index = models.FloatField()
#     cite = models.CharField(max_length=50)
#     file = models.ForeignKey(Transcript, on_delete=models.CASCADE)

class Comment(TimestampedModel):
    testimony = models.ForeignKey(
        Testimony, on_delete=models.CASCADE, related_name="comments"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()

    def __str__(self):
        return f"{self.user.email} on Testimony {self.testimony.id}"
    
class Highlights(TimestampedModel):
    testimony = models.ForeignKey(
        Testimony, on_delete=models.CASCADE, related_name="highlights"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    highlight = models.TextField()

    def __str__(self):
        return f"{self.user.email} on Testimony {self.testimony.id}"