from django.db import models
from django.contrib.auth.models import *


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    def __str__(self):
        return self.name

class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    def __str__(self):
        return self.name


# Module Master Table
class Module(models.Model):
    name = models.CharField(max_length=100, unique=True)
    menu_title = models.CharField(max_length=100, blank=True, null=True)
    headings = models.JSONField(default=list, blank=True, null=True)
    # ADD THIS: Store original display names
    # heading_display_map = models.JSONField(default=dict, blank=True, null=True)
    html_file = models.CharField(max_length=255, blank=True, null=True)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='submenus'
    )

    def __str__(self):
        return self.name

    def get_display_headings(self):
        """Return headings with their display names"""
        if not self.heading_display_map:
            return self.headings
        return [self.heading_display_map.get(h, h) for h in self.headings]

    class Meta:
        verbose_name = "Module Master"
        verbose_name_plural = "Module Masters"
  

# User Module Provision Table
class UserModuleProvision(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='module_provisions')
    module_name = models.CharField(max_length=255)
    headings = models.JSONField(default=list, blank=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)  # <-- Add this line
    created_at = models.DateTimeField(auto_now_add=True)
    
    

    def __str__(self):
        return f"{self.user.username} - {self.module_name}"
    
    


class UserManagementTable(models.Model):
    """
    This model is for Django admin panel display only.
    It does not create a new table, but allows you to register a custom admin list.
    """
    class Meta:
        managed = False
        verbose_name = "User Management Table"
        verbose_name_plural = "User Management Table"

    @property
    def user_id(self):
        return self.user.id

    @property
    def full_name(self):
        return f"{self.user.first_name} {self.user.last_name}"

    @property
    def email(self):
        return self.user.email

    @property
    def department(self):
        try:
            return self.user.userprofile.department.name
        except Exception:
            return ""

    @property
    def role(self):
        try:
            return self.user.userprofile.role.name
        except Exception:
            return ""

    @property
    def manager(self):
        try:
            return self.user.userprofile.manager
        except Exception:
            return ""

    @property
    def status(self):
        try:
            return self.user.userprofile.employment_status
        except Exception:
            return ""

    @property
    def modules(self):
        return ", ".join(
            UserModuleProvision.objects.filter(user=self.user).values_list("module_name", flat=True)
        )

    @property
    def created(self):
        return self.user.date_joined

    @property
    def actions(self):
        return "Edit/Delete"

# ...existing code...

from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True)
    manager = models.CharField(max_length=100, blank=True, null=True)
    employment_status = models.CharField(max_length=20, choices=[('On-role', 'On-role'), ('Off-role', 'Off-role')])

    def __str__(self):
        return self.user.username

from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
        
        
