"""Registration, sign-in/out, profiles and password hashing."""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import PassengerProfile, User
from apps.core.testing import PASSWORD, make_user
from apps.operations.models import ActivityLog


class RegistrationTests(TestCase):
    def post_register(self, **overrides):
        data = {
            "first_name": "Isha", "last_name": "Kapoor", "username": "isha", "email": "isha@example.test",
            "phone": "9876543210", "password1": "Str0ng!Pass#2026", "password2": "Str0ng!Pass#2026",
            "accept_terms": "on",
        }
        data.update(overrides)
        return self.client.post(reverse("accounts:register"), data)

    def test_register_creates_passenger_with_profile_and_logs_in(self):
        response = self.post_register()
        self.assertRedirects(response, reverse("bookings:passenger_dashboard"))
        user = User.objects.get(username="isha")
        self.assertEqual(user.role, User.Role.PASSENGER)
        self.assertTrue(PassengerProfile.objects.filter(user=user).exists())
        self.assertNotEqual(user.password, "Str0ng!Pass#2026")  # hashed
        self.assertTrue(user.password.startswith(("pbkdf2_", "argon2", "bcrypt")))
        self.assertTrue(ActivityLog.objects.filter(action="REGISTER", actor=user).exists())
        self.assertEqual(self.client.get(reverse("bookings:passenger_dashboard")).status_code, 200)

    def test_register_validation(self):
        make_user("taken")
        cases = [
            {"username": "taken"},
            {"email": "taken@example.test"},
            {"password2": "different"},
            {"password1": "12345678", "password2": "12345678"},
            {"phone": "12345"},
            {"accept_terms": ""},
        ]
        for case in cases:
            with self.subTest(case=case):
                response = self.post_register(**case)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(User.objects.filter(username=case.get("username", "isha"), role="PASSENGER",
                                                     email="isha@example.test").exists())

    def test_registration_cannot_escalate_role(self):
        self.post_register(role="ADMIN")
        self.assertEqual(User.objects.get(username="isha").role, User.Role.PASSENGER)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = make_user("ravi")

    def test_login_with_username_or_email_and_role_redirect(self):
        r = self.client.post(reverse("accounts:login"), {"username": "ravi", "password": PASSWORD})
        self.assertRedirects(r, reverse("core:post_login"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("core:post_login")), reverse("bookings:passenger_dashboard"))
        self.client.logout()
        r = self.client.post(reverse("accounts:login"), {"username": "RAVI@example.test", "password": PASSWORD})
        self.assertEqual(r.status_code, 302)

    def test_role_based_landing(self):
        for role, target in [(User.Role.TT, "operations:dashboard"), (User.Role.ADMIN, "adminpanel:dashboard")]:
            u = make_user(f"user_{role.lower()}", role=role)
            self.client.force_login(u)
            self.assertRedirects(self.client.get(reverse("core:post_login")), reverse(target))

    def test_wrong_password_and_inactive(self):
        r = self.client.post(reverse("accounts:login"), {"username": "ravi", "password": "nope"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "not correct")
        self.assertTrue(ActivityLog.objects.filter(action="LOGIN_FAILED").exists())
        self.user.is_active = False
        self.user.save()
        r = self.client.post(reverse("accounts:login"), {"username": "ravi", "password": PASSWORD})
        self.assertEqual(r.status_code, 200)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        r = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(r, reverse("core:home"))
        self.assertEqual(self.client.get(reverse("bookings:passenger_dashboard")).status_code, 302)

    def test_csrf_enforced_on_login(self):
        client = self.client_class(enforce_csrf_checks=True)
        r = client.post(reverse("accounts:login"), {"username": "ravi", "password": PASSWORD})
        self.assertEqual(r.status_code, 403)


class ProfileTests(TestCase):
    def test_update_profile_and_change_password(self):
        user = make_user("asha")
        self.client.force_login(user)
        r = self.client.post(reverse("accounts:profile"), {
            "action": "details", "u-first_name": "Asha", "u-last_name": "Rao", "u-email": "asha.rao@example.test",
            "u-phone": "9123456780", "p-gender": "F", "p-preferred_berth": "LB", "p-preferred_class": "SL",
            "p-city": "Pune", "p-state": "Maharashtra", "p-address": "", "p-date_of_birth": "1999-02-03",
        })
        self.assertRedirects(r, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.email, "asha.rao@example.test")
        self.assertEqual(user.passenger_profile.preferred_berth, "LB")
        r = self.client.post(reverse("accounts:profile"), {
            "action": "password", "pw-old_password": PASSWORD,
            "pw-new_password1": "An0ther!Secret#9", "pw-new_password2": "An0ther!Secret#9",
        })
        self.assertRedirects(r, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("An0ther!Secret#9"))
