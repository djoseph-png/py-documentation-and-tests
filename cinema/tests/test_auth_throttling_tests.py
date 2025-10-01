import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

MOVIE_LIST_URL = reverse("cinema:movie-list")
TOKEN_URL = reverse("cinema:token_obtain_pair")
TOKEN_REFRESH_URL = reverse("cinema:token_refresh")
SCHEMA_URL = reverse("schema")  # endpoint público para throttling anônimo


class JwtAuthTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.email = "jwtuser@example.com"
        self.password = "password123"
        get_user_model().objects.create_user(
            email=self.email, password=self.password
        )

    def test_obtain_jwt_and_access_protected(self):
        res = self.client.post(
            TOKEN_URL, {"email": self.email, "password": self.password}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("access", res.data)
        access = res.data["access"]

        # Usa o token para tentar criar (deve falhar p/ não-admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        res = self.client.post(
            MOVIE_LIST_URL,
            {"title": "T", "description": "D", "duration": 90},
            format="json",
        )
        # Se a regra de negócio for somente admin pode criar, esperamos 403
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_refresh_jwt(self):
        res = self.client.post(
            TOKEN_URL, {"email": self.email, "password": self.password}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", res.data)

        refresh = res.data["refresh"]
        res2 = self.client.post(
            TOKEN_REFRESH_URL, {"refresh": refresh}, format="json"
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertIn("access", res2.data)


class ThrottlingTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()  # evita interferência entre testes

    @override_settings(
        REST_FRAMEWORK={
            **getattr(settings, "REST_FRAMEWORK", {}),
            "DEFAULT_THROTTLE_CLASSES": (
                "rest_framework.throttling.AnonRateThrottle",
                "rest_framework.throttling.UserRateThrottle",
            ),
            "DEFAULT_THROTTLE_RATES": {"anon": "10/minute", "user": "30/minute"},
        }
    )
    def test_anon_throttling_limit(self):
        # usa endpoint público para garantir 200 até o limite
        for i in range(10):
            res = self.client.get(SCHEMA_URL)
            self.assertEqual(
                res.status_code, status.HTTP_200_OK, msg=f"Falhou no request {i+1}"
            )
        blocked = self.client.get(SCHEMA_URL)
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("throttled", str(blocked.data).lower())

    @override_settings(
        REST_FRAMEWORK={
            **getattr(settings, "REST_FRAMEWORK", {}),
            "DEFAULT_THROTTLE_CLASSES": (
                "rest_framework.throttling.AnonRateThrottle",
                "rest_framework.throttling.UserRateThrottle",
            ),
            "DEFAULT_THROTTLE_RATES": {"anon": "10/minute", "user": "30/minute"},
        }
    )
    def test_user_throttling_limit(self):
        email = "throttle@example.com"
        password = "pass12345"
        user = get_user_model().objects.create_user(email=email, password=password)
        self.client.force_authenticate(user)

        # Preferir um endpoint GET que retorne 200 consistentemente (listagem)
        for i in range(30):
            res = self.client.get(MOVIE_LIST_URL)
            # Espera-se 200 até atingir o limite
            self.assertEqual(
                res.status_code, status.HTTP_200_OK, msg=f"Falhou no request {i+1}"
            )

        blocked = self.client.get(MOVIE_LIST_URL)
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("throttled", str(blocked.data).lower())

        # Minimiza flakiness local
        time.sleep(0.2)
