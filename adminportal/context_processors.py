from django.core.cache import cache
from adminportal.models import UserModuleProvision, Module

# Cache key and TTL for module list (same for all authenticated users)
_MODULE_CACHE_KEY = 'all_module_names'
_MODULE_CACHE_TTL = 300  # 5 minutes


def user_permissions(request):
    """Add user permission context to all templates.

    Default behavior: any authenticated user sees all modules.
    This preserves `is_admin` flag for legacy checks but returns
    the full module list so menus are visible by default.
    """
    if request.user.is_authenticated:
        is_admin = request.user.is_superuser
        try:
            # Use cached module list to avoid DB hit on every request
            allowed_modules = cache.get(_MODULE_CACHE_KEY)
            if allowed_modules is None:
                allowed_modules = list(Module.objects.values_list('name', flat=True))
                cache.set(_MODULE_CACHE_KEY, allowed_modules, _MODULE_CACHE_TTL)
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