from django.urls import path

from apps.core.views import AttachmentDestroyView, AttachmentDownloadView, AttachmentListCreateView

urlpatterns = [
    path("attachments/", AttachmentListCreateView.as_view(), name="attachment-list-create"),
    path("attachments/<int:pk>/", AttachmentDestroyView.as_view(), name="attachment-destroy"),
    path("attachments/<int:pk>/download/", AttachmentDownloadView.as_view(), name="attachment-download"),
]
