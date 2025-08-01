from rest_framework import serializers
from .models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'msal_id']

class FetchUserIdSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [ 'msal_id']
