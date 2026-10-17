import json

from django.core.management.base import BaseCommand

from dashboard.services import research_statistics


class Command(BaseCommand):
    help = "Export anonymous aggregate research metrics as JSON."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(research_statistics(), default=str, indent=2))
