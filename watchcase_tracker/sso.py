import os
import uuid
import logging
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth import login
from django.contrib.auth.models import User, Group
from django.http import HttpResponseBadRequest, HttpResponse
import msal

logger = logging.getLogger(__name__)


def microsoft_login(request):
    """Start the Microsoft OIDC Authorization Code flow by redirecting user."""
    if not settings.MSAL_CLIENT_ID or not settings.MSAL_CLIENT_SECRET:
        logger.error("MSAL client id/secret not configured in settings.")
        return HttpResponseBadRequest("SSO not configured.")

    # create and persist state to protect against CSRF
    state = str(uuid.uuid4())
    request.session['msal_state'] = state

    authority = "https://login.microsoftonline.com/04132f71-f746-4a5b-a30e-66ea6d16714c"
    app = msal.ConfidentialClientApplication(
        client_id=settings.MSAL_CLIENT_ID,
        client_credential=settings.MSAL_CLIENT_SECRET,
        authority=authority,
    )

    redirect_uri = request.build_absolute_uri(settings.MSAL_REDIRECT_PATH)
    auth_url = app.get_authorization_request_url(
        scopes=settings.MSAL_SCOPES,
        state=state,
        redirect_uri=redirect_uri,
    )

    return redirect(auth_url)


def microsoft_callback(request):
    """Handle the redirect back from Microsoft and sign the user into Django."""
    error = request.GET.get('error')
    if error:
        desc = request.GET.get('error_description') or error
        logger.error("MSAL returned error: %s", desc)
        return HttpResponseBadRequest(f"Authentication error: {desc}")

    state = request.GET.get('state')
    session_state = request.session.get('msal_state')
    if not state or not session_state or state != session_state:
        logger.warning("State mismatch in MSAL callback (session=%s, returned=%s)", session_state, state)
        return HttpResponseBadRequest("State mismatch or missing. Potential CSRF detected.")

    code = request.GET.get('code')
    if not code:
        logger.error("No authorization code received in callback.")
        return HttpResponseBadRequest("Authorization code not found in callback.")

    authority = "https://login.microsoftonline.com/04132f71-f746-4a5b-a30e-66ea6d16714c"
    app = msal.ConfidentialClientApplication(
        client_id=settings.MSAL_CLIENT_ID,
        client_credential=settings.MSAL_CLIENT_SECRET,
        authority=authority,
    )

    redirect_uri = request.build_absolute_uri(settings.MSAL_REDIRECT_PATH)
    try:
        result = app.acquire_token_by_authorization_code(
            code,
            scopes=settings.MSAL_SCOPES,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        logger.exception("Exception while acquiring token: %s", e)
        return HttpResponseBadRequest("Token exchange failed.")

    if not result or 'error' in result:
        logger.error("Token acquisition failed: %s", result)
        return HttpResponseBadRequest("Token acquisition failed.")

    # ID token claims contain user info for OIDC
    id_token_claims = result.get('id_token_claims', {})
    email = id_token_claims.get('preferred_username') or id_token_claims.get('email') or id_token_claims.get('upn')
    name = id_token_claims.get('name') or ''

    if not email:
        logger.error("ID token did not contain an email/username claim: %s", id_token_claims)
        return HttpResponseBadRequest("Unable to determine user identity from ID token.")

    # Create or get Django user. Use email as username to keep uniqueness.
    first_name = ''
    last_name = ''
    if name:
        parts = name.split()
        first_name = parts[0]
        last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''

    user, created = User.objects.get_or_create(
        username=email,
        defaults={'email': email, 'first_name': first_name, 'last_name': last_name, 'is_active': True},
    )

    if created:
        # New user: optionally set unusable password and add to default group
        user.set_unusable_password()
        default_group = os.environ.get('MSAL_DEFAULT_GROUP')
        if default_group:
            grp, _ = Group.objects.get_or_create(name=default_group)
            user.groups.add(grp)
        user.save()

    # Log the user in via Django session-based auth
    login(request, user)

    # Clean up state cookie
    try:
        del request.session['msal_state']
    except Exception:
        pass

    # Redirect to dashboard / home
    return redirect(settings.LOGIN_REDIRECT_URL or '/home/')
