import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "community_donation.settings")
from django.core.management import execute_from_command_line

execute_from_command_line(sys.argv)
