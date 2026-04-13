import time
import logging

logger = logging.getLogger(__name__)

# Prefixes to skip logging (static/media files don't need latency tracking)
_SKIP_PREFIXES = ('/static/', '/media/', '/favicon.ico')


class LatencyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip timing for static/media files to reduce I/O overhead
        if request.path.startswith(_SKIP_PREFIXES):
            return self.get_response(request)
        start_time = time.time()
        response = self.get_response(request)
        duration = time.time() - start_time
        logger.info(f"Request to {request.path} took {duration:.4f} seconds")
        return response