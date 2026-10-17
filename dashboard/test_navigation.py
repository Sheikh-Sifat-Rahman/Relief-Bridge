from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.services import approve_role, request_role


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.startswith(("/donor/", "/seeker/", "/volunteer/")):
                self.urls.append(href)


class LoginAndNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            "nav_admin", "nav-admin@example.invalid", "Navigation-password-123"
        )
        cls.user = User.objects.create_user(
            "nav_user", "nav-user@example.invalid", "Navigation-password-123"
        )
        for role in ["DONOR", "VOLUNTEER", "AID_SEEKER"]:
            approve_role(cls.admin, request_role(cls.user, role))

    def test_admin_cannot_login_through_public_form_with_email_or_username(self):
        for identifier in [self.admin.email, self.admin.username]:
            response = self.client.post(
                reverse("accounts:login"),
                {"username": identifier, "password": "Navigation-password-123"},
            )
            self.assertContains(response, "must use Log in as administration")
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_login_does_not_redirect_into_user_dashboard(self):
        response = self.client.post(
            reverse("management:login") + "?next=/dashboard/",
            {"username": self.admin.email, "password": "Navigation-password-123"},
        )
        self.assertRedirects(response, reverse("management:home"))

    def test_regular_user_email_login_still_works(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.user.email, "password": "Navigation-password-123"},
        )
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_all_dashboard_segments_and_their_navigation_open(self):
        self.client.force_login(self.user)
        overview = self.client.get(reverse("dashboard:home"))
        links = Links()
        links.feed(overview.content.decode())
        self.assertEqual(set(links.urls), {"/donor/", "/volunteer/", "/seeker/"})
        for dashboard in links.urls:
            page = self.client.get(dashboard)
            self.assertEqual(page.status_code, 200, dashboard)
            inner_links = Links()
            inner_links.feed(page.content.decode())
            for url in inner_links.urls:
                self.assertEqual(self.client.get(url).status_code, 200, url)
            self.assertNotContains(page, "Donor profile")
            self.assertNotContains(page, "Household profile")
            self.assertNotContains(page, "Edit profile")

    def test_profile_editing_is_below_summary_and_roles(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "Edit donor profile")
        self.assertContains(response, "Edit household profile")
        html = response.content.decode()
        self.assertLess(html.index("Profile details"), html.index('id="edit-profile"'))
        self.assertLess(html.index("Your roles"), html.index('id="edit-profile"'))
        for route in ["donor:profile", "accounts:household"]:
            editor = self.client.get(reverse(route))
            self.assertEqual(editor.status_code, 200)
            self.assertContains(editor, "Back to Profile")

    def test_pending_users_can_complete_profile_but_not_use_role_pages(self):
        user = User.objects.create_user("nav_pending", "nav-pending@example.invalid")
        request_role(user, "DONOR")
        request_role(user, "AID_SEEKER")
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "Edit household profile")
        self.assertEqual(
            self.client.get(reverse("accounts:household")).status_code, 200
        )
        for route in ["donor:home", "seeker:home", "donor:money", "seeker:create"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_role_subpages_have_distinct_titles_and_content(self):
        self.client.force_login(self.user)
        for route, title in [
            ("donor:donations", "My donations"),
            ("donor:history", "Donation history"),
            ("seeker:requests", "My aid requests"),
            ("seeker:received", "Aid received"),
            ("seeker:history", "Distribution history"),
            ("volunteer:assignments", "My assignments"),
            ("volunteer:deliveries", "My deliveries"),
        ]:
            response = self.client.get(reverse(route))
            self.assertContains(response, f"<h1>{title}</h1>", html=True)
        self.assertNotContains(
            self.client.get(reverse("seeker:requests")),
            "Approved aid &amp; distribution history",
        )
        self.assertNotContains(
            self.client.get(reverse("seeker:received")), "<h3>Your requests</h3>"
        )
        self.assertNotContains(
            self.client.get(reverse("donor:history")), "Goods by category"
        )

    def test_admin_dashboard_and_profile_redirects(self):
        self.client.force_login(self.admin)
        self.assertRedirects(
            self.client.get(reverse("dashboard:home")), reverse("management:home")
        )
        self.assertRedirects(
            self.client.get(reverse("accounts:profile")), reverse("management:profile")
        )
        response = self.client.get(reverse("management:home"))
        self.assertContains(response, "<h1>Review center</h1>", html=True)
        self.assertNotContains(response, "Admin dashboard")
        self.assertNotContains(response, ">Admin profile</a>")

    def test_admin_menu_persists_across_operations_and_public_pages(self):
        self.client.force_login(self.admin)
        for route in [
            "management:index",
            "management:home",
            "management:profile",
            "admin:index",
            "admin:donations_donation_changelist",
            "home",
            "campaigns:list",
        ]:
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 200, route)
            self.assertContains(response, "<summary>My dashboard</summary>", html=True)
            self.assertContains(response, reverse("management:home"))
            self.assertContains(response, reverse("admin:index"))
            self.assertContains(response, reverse("management:profile"))

    def test_operations_login_also_lands_on_admin_dashboard(self):
        response = self.client.post(
            reverse("admin:login") + "?next=" + reverse("admin:index"),
            {"username": self.admin.email, "password": "Navigation-password-123"},
        )
        self.assertRedirects(response, reverse("management:home"))
