from django.shortcuts import render
from rest_framework import viewsets
from .models import User
from .serializers import UserSerializer
from rest_framework.response import Response
from rest_framework.decorators import action
from django.utils import timezone
from rest_framework import status

# Create your views here.
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("id")
    serializer_class = UserSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        # 🔍 Automatically applies pagination (respects ?page=, ?page_size=)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        # Fallback (unlikely used)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=["post"], url_path="create-user")
    def create_user(self, request):
        email = request.data.get("email")
        name = request.data.get("name", "")
        msal_id = request.data.get("msal_id", "")
        last_login = request.data.get("last_login")

        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "name": name,
                "msal_id": msal_id,
                "last_login": last_login or timezone.now()
            }
        )

        if created:
            return Response({"message": "User created.", "user_id": user.id}, status=status.HTTP_201_CREATED)
        else:
            return Response({"message": "User already exists."}, status=status.HTTP_200_OK)
        
    @action(detail=False, methods=["post"], url_path="get-user-id")
    def get_user_id(self, request):
        msal_id = request.data.get("msal_id")

        if not msal_id:
            return Response({"error": "Msal id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(msal_id=msal_id)
            return Response({"id": user.id}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "User with provided msal_id not found."}, status=status.HTTP_404_NOT_FOUND)