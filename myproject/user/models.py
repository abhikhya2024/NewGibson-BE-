from django.db import models
from django.contrib.auth.models import AbstractUser,BaseUserManager
import os
import time
# Create your models here.

def profile(instance, filename):
    ext = filename.split('.')[-1]
    filename = f"profilepic_{int(time.time() * 1000)}.{ext}"
    return os.path.join('profile_pictures', filename)

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email must be set")
        extra_fields.setdefault('is_active', True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
 
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
 
        return self.create_user(email, password, **extra_fields)
 
class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255, blank=True)  # ← Add this field
    msal_id = models.CharField(max_length=255, blank=True, null=True)
    profile_picture = models.ImageField(upload_to=profile, null=True, blank=True)
    type = models.CharField(max_length=10, blank=True)
    last_active = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email
