from django.urls import path

from apps.core.views import AttachmentDestroyView, AttachmentListCreateView

urlpatterns = [
    path("attachments/", AttachmentListCreateView.as_view(), name="attachment-list-create"),
    path("attachments/<int:pk>/", AttachmentDestroyView.as_view(), name="attachment-destroy"),
]
