from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Allow signing in with either the username or the e-mail address."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        lookup = {"email__iexact": username.strip()} if "@" in username else {"username__iexact": username.strip()}
        try:
            user = User.objects.get(**lookup)
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            User().set_password(password)  # equalise timing with the success path
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
