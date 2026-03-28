from adminportal.models import UserModuleProvision, Module


def user_permissions(request):
    """Add user permission context to all templates.

    Default behavior: any authenticated user sees all modules.
    This preserves `is_admin` flag for legacy checks but returns
    the full module list so menus are visible by default.
    """
    if request.user.is_authenticated:
        is_admin = request.user.is_superuser
        try:
            # Return all module names so authenticated users see full menu
            allowed_modules = list(Module.objects.values_list('name', flat=True))
        except Exception:
            # Fallback: if Module table missing or error, try per-user provisions
            try:
                provisions = UserModuleProvision.objects.filter(user=request.user)
                allowed_modules = [provision.module_name for provision in provisions]
            except Exception:
                allowed_modules = []

        return {
            'is_admin': is_admin,
            'allowed_modules': allowed_modules,
        }

    return {
        'is_admin': False,
        'allowed_modules': [],
    }