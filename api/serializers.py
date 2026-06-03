"""Serializers for the read API — Job and its Artifact audit trail."""

from __future__ import annotations

from rest_framework import serializers

from jobs.models import Artifact, Job


class ArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Artifact
        fields = ("stage", "kind", "path", "created_at")


class JobSerializer(serializers.ModelSerializer):
    artifacts = ArtifactSerializer(many=True, read_only=True)

    class Meta:
        model = Job
        fields = (
            "id",
            "status",
            "current_stage",
            "failed_stage",
            "error_detail",
            "theme",
            "preset_name",
            "output_path",
            "suggested_caption",
            "created_at",
            "updated_at",
            "artifacts",
        )
