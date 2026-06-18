from django.conf import settings

class WesternUnionHostBypassMiddleware:
    """
    Middleware to dynamically allow any host for the Western Union/Pago Facil endpoints.
    If the request path matches one of the 3 Western Union endpoints, it overrides
    the `request.get_host` method to return a valid allowed host from settings.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/v2/finance/pagofacil/api/'):
            # Find a valid host from settings.ALLOWED_HOSTS to spoof
            valid_host = 'localhost'
            for host in settings.ALLOWED_HOSTS:
                if host and host != '*':
                    # Handle host values like '.example.com' or 'example.com'
                    valid_host = host.lstrip('.')
                    break
            
            # Dynamically override the request.get_host method
            request.get_host = lambda: valid_host
            
        return self.get_response(request)
