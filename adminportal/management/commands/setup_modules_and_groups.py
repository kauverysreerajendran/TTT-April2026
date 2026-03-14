"""
Management command: setup_modules_and_groups
============================================
Creates the five fixed User Category groups (if they don't exist) and
links each group to the Module records whose menu_title matches the
category's mapped value.

Run once (and re-run whenever new modules are added):
    python manage.py setup_modules_and_groups
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from adminportal.models import Module

# ---------------------------------------------------------------------------
# Mapping: group name  →  list of Module.menu_title values to link
# ---------------------------------------------------------------------------
CATEGORY_MENU_MAP = {
    "DP User":  ["Day Planning"],
    "IS User":  ["Input Screening"],
    "BQC User": ["Brass QC"],
    "IQF User": ["IQF"],
    "BA User":  ["Brass Audit"],
}


class Command(BaseCommand):
    help = (
        "Create the 5 fixed User Category groups and link them to their "
        "respective modules via the Module.groups ManyToMany field."
    )

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.MIGRATE_HEADING("Setting up User Category groups …\n"))

        for group_name, menu_titles in CATEGORY_MENU_MAP.items():
            group, created = Group.objects.get_or_create(name=group_name)
            action = "Created  " if created else "Exists   "

            modules = Module.objects.filter(menu_title__in=menu_titles)
            group.modules.set(modules)          # replace any previous links

            module_names = [m.name for m in modules] or ["(no modules found — check menu_title values)"]
            self.stdout.write(
                f"  {action} '{group_name}'  →  {module_names}"
            )

        self.stdout.write(self.style.SUCCESS("\nDone. Re-run this command any time new modules are added."))