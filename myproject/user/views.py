from django.shortcuts import render
from rest_framework import viewsets
from .models import User
from .serializers import UserSerializer
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