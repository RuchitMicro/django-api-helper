"""Focused regression tests runnable with ``python -m unittest django_api_helper.tests``."""

import unittest

from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="django-api-helper-tests",
        INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "rest_framework", "django_filters"],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["testserver"],
        USE_TZ=True,
    )

import django

django.setup()

from django.db import connection, models
from rest_framework import serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from django_api_helper.decorators import check_table_permissions, error_handling
from django_api_helper.pagination import CustomPageNumberPagination
from django_api_helper.serializers import create_model_serializer, serialize_related_object
from django_api_helper.views import GenericCRUDView


class Account(models.Model):
    username = models.CharField(max_length=32)
    password = models.CharField(max_length=128)

    class Meta:
        app_label = "helper_tests"
        ordering = ["id"]


class Article(models.Model):
    title = models.CharField(max_length=64)
    owner = models.ForeignKey(Account, on_delete=models.CASCADE)

    class Meta:
        app_label = "helper_tests"
        ordering = ["id"]


class ArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Article
        fields = ["id", "title", "owner"]


class UnsafeAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ["id", "username", "password"]


class ArticleView(GenericCRUDView):
    model = Article
    serializer_class = ArticleSerializer
    pagination_class = None


class OneItemPagination(CustomPageNumberPagination):
    page_size = 1


class PaginatedArticleView(ArticleView):
    pagination_class = OneItemPagination


class AggregateArticleView(ArticleView):
    allow_aggregate = True
    allowed_aggregate_methods = ["count"]
    allowed_aggregate_fields = ["id"]


class AccountView(GenericCRUDView):
    model = Account
    serializer_class = UnsafeAccountSerializer
    pagination_class = None


class CRUDRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            editor.create_model(Account)
            editor.create_model(Article)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(Article)
            editor.delete_model(Account)
        super().tearDownClass()

    def setUp(self):
        Article.objects.all().delete()
        Account.objects.all().delete()
        self.owner = Account.objects.create(username="ada", password="hashed-password")
        self.article = Article.objects.create(title="A safe article", owner=self.owner)
        self.factory = APIRequestFactory()

    def test_dynamic_serializer_hides_password_unless_explicitly_enabled(self):
        self.assertNotIn("password", create_model_serializer(Account).Meta.fields)
        self.assertIn("password", create_model_serializer(Account, include_sensitive_fields=True).Meta.fields)

    def test_nested_output_redacts_related_password(self):
        response = ArticleView.as_view()(self.factory.get("/articles/?nested=1&depth=2"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["owner"]["username"], "ada")
        self.assertNotIn("password", response.data[0]["owner"])

    def test_headers_cannot_restore_a_sensitive_custom_serializer_field(self):
        response = AccountView.as_view()(self.factory.get("/accounts/", HTTP_X_INCLUDE="username,password"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [{"username": "ada"}])

    def test_sensitive_opt_in_is_explicit(self):
        output = serialize_related_object(self.owner, include_sensitive_fields=True)
        self.assertEqual(output["password"], "hashed-password")

    def test_include_and_exclude_headers_apply_to_unpaginated_and_nested_output(self):
        request = self.factory.get("/articles/?nested=1", HTTP_X_INCLUDE=" title ; owner ", HTTP_X_EXCLUDE="owner")
        response = ArticleView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [{"title": "A safe article"}])

    def test_projection_applies_to_paginated_and_detail_output(self):
        Article.objects.create(title="A second article", owner=self.owner)
        response = PaginatedArticleView.as_view()(self.factory.get("/articles/", HTTP_X_INCLUDE="title"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [{"title": "A safe article"}])
        response = ArticleView.as_view()(self.factory.get(f"/articles/?pk={self.article.pk}", HTTP_X_EXCLUDE="owner"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("owner", response.data)

    def test_invalid_depth_and_ordering_are_safe_validation_errors(self):
        for url in ("/articles/?depth=not-a-number", "/articles/?order_by=missing"):
            response = ArticleView.as_view()(self.factory.get(url))
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["code"], "validation_error")
            self.assertIn("errors", response.data)

    def test_filter_and_aggregate_contracts_remain_available(self):
        response = AggregateArticleView.as_view()(self.factory.get("/articles/?title=safe&aggregate=count:id", HTTP_X_INCLUDE="title"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"aggregates": {"count_id": 1}})

    def test_missing_patch_pk_is_safe_validation_error(self):
        class User:
            def has_perm(self, permission):
                return True

        request = self.factory.patch("/articles/", {"title": "Updated"}, format="json")
        force_authenticate(request, user=User())
        response = ArticleView.as_view()(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"], {"pk": ["This query parameter is required."]})

    def test_create_patch_delete_and_detail_preserve_success_shapes(self):
        class User:
            def has_perm(self, permission):
                return True

        create_request = self.factory.post("/articles/", {"title": "Created", "owner": self.owner.pk}, format="json")
        force_authenticate(create_request, user=User())
        created = ArticleView.as_view()(create_request)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["title"], "Created")

        object_id = created.data["id"]
        patch_request = self.factory.patch(f"/articles/?pk={object_id}", {"title": "Updated"}, format="json")
        force_authenticate(patch_request, user=User())
        updated = ArticleView.as_view()(patch_request)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["title"], "Updated")

        detail = ArticleView.as_view()(self.factory.get(f"/articles/?pk={object_id}"))
        self.assertEqual(detail.data["id"], object_id)
        delete_request = self.factory.delete(f"/articles/?pk={object_id}")
        force_authenticate(delete_request, user=User())
        deleted = ArticleView.as_view()(delete_request)
        self.assertEqual(deleted.status_code, 204)

    def test_unexpected_error_does_not_expose_exception_text(self):
        class BrokenView:
            model = Article

            @error_handling
            def get(self, request):
                raise RuntimeError("database password is secret")

        response = BrokenView().get(self.factory.get("/broken/"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["code"], "internal_error")
        self.assertNotIn("secret", str(response.data))

    def test_permission_uses_http_method_specific_codename(self):
        captured = []

        class User:
            def has_perm(self, permission):
                captured.append(permission)
                return True

        class View:
            app_label = "helper_tests"
            model_name = "article"

            @check_table_permissions
            def handler(self, request):
                return "ok"

        request = self.factory.post("/articles/")
        request.user = User()
        self.assertEqual(View().handler(request), "ok")
        self.assertEqual(captured, ["helper_tests.add_article"])


if __name__ == "__main__":
    unittest.main()
