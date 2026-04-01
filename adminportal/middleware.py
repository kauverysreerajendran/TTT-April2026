import base64
from django.utils.crypto import get_random_string

class CSPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        nonce = base64.b64encode(get_random_string(16).encode()).decode()
        request.csp_nonce = nonce
        response = self.get_response(request)
        response['Content-Security-Policy'] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://unpkg.com https://cdn.jsdelivr.net/npm/sweetalert2@11 'strict-dynamic';"
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://*.lottiefiles.com https://fonts.gstatic.com https://cdnjs.cloudflare.com https://demo.bootstrapdash.com;"
            "img-src 'self' https://assets2.lottiefiles.com/packages/lf20_uiyqFZ.json https://assets10.lottiefiles.com/packages/lf20_jcikwtux.json https://demo.bootstrapdash.com/skydash/themes/assets/images/logo-mini.svg https://demo.bootstrapdash.com/skydash/themes/assets/images/logo.svg https://demo.bootstrapdash.com/skydash/themes/assets/images/dashboard/people.svg data:; "
            "connect-src 'self' https://assets2.lottiefiles.com/packages/lf20_uiyqFZ.json https://assets10.lottiefiles.com/packages/lf20_jcikwtux.json;"            
            "frame-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self';"
        )
        return response