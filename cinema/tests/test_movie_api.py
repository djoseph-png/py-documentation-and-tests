# cinema/tests/test_movie_api.py

import os
import tempfile
from datetime import datetime

from PIL import Image
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from cinema.models import Actor, Genre, Movie
from django.core.cache import cache

# =======================================================================
#  URLs
# =======================================================================
MOVIES_URL = reverse("cinema:movie-list")


def detail_url(movie_id: int) -> str:
    """Retorna a URL de detalhe para um filme específico."""
    return reverse("cinema:movie-detail", args=[movie_id])


def image_upload_url(movie_id: int) -> str:
    """Retorna a URL para upload de imagem de um filme."""
    return reverse("cinema:movie-upload-image", args=[movie_id])


# =======================================================================
#  Helper Functions
# =======================================================================
def create_user(is_staff: bool = False, **params):
    """Cria e retorna um novo usuário."""
    defaults = {"email": "user@example.com", "password": "password123"}
    defaults.update(params)
    user = get_user_model().objects.create_user(**defaults)
    if is_staff:
        user.is_staff = True
        user.save()
    return user


def sample_genre(**params) -> Genre:
    """Cria e retorna um gênero de amostra."""
    defaults = {"name": "Test Genre"}
    defaults.update(params)
    return Genre.objects.create(**defaults)


def sample_actor(**params) -> Actor:
    """Cria e retorna um ator de amostra."""
    defaults = {"first_name": "Test", "last_name": "Actor"}
    defaults.update(params)
    return Actor.objects.create(**defaults)


def sample_movie(**params) -> Movie:
    """Cria e retorna um filme de amostra."""
    genres = params.pop("genres", None)
    actors = params.pop("actors", None)
    defaults = {"title": "Sample Movie", "description": "Desc", "duration": 120}
    defaults.update(params)
    movie = Movie.objects.create(**defaults)
    if genres:
        movie.genres.set(genres)
    if actors:
        movie.actors.set(actors)
    return movie


TEST_REST_FRAMEWORK_SETTINGS = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_THROTTLE_CLASSES": (),
    "DEFAULT_THROTTLE_RATES": {},
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
}


# =======================================================================
#  Classes de Teste
# =======================================================================
@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK_SETTINGS)
class PublicMovieApiTests(APITestCase):
    """Testa o acesso não autenticado à API de Filmes."""
    def test_auth_required(self):
        """Verifica se a autenticação é necessária para acessar o endpoint."""
        res = self.client.get(MOVIES_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK_SETTINGS)
class PrivateMovieApiTests(APITestCase):
    """Testa o acesso autenticado à API de Filmes."""
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_authenticate(self.user)

    def test_filter_movies_by_genres(self):
        """Testa a filtragem de filmes por IDs de gênero."""
        genre1 = sample_genre(name="Action")
        genre2 = sample_genre(name="Comedy")
        movie1 = sample_movie(title="Movie with Action", genres=[genre1])
        movie2 = sample_movie(title="Movie with Comedy", genres=[genre2])
        sample_movie(title="Movie without these genres")

        res = self.client.get(MOVIES_URL, {"genres": f"{genre1.id},{genre2.id}"})
        results = res.data["results"]
        titles = [movie["title"] for movie in results]

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(results), 2)
        self.assertIn(movie1.title, titles)
        self.assertIn(movie2.title, titles)

    def test_filter_movies_by_actors(self):
        """Testa a filtragem de filmes por IDs de ator."""
        actor1 = sample_actor(first_name="Actor", last_name="One")
        actor2 = sample_actor(first_name="Actor", last_name="Two")
        movie1 = sample_movie(title="Movie with Actor One", actors=[actor1])
        movie2 = sample_movie(title="Movie with Actor Two", actors=[actor2])
        sample_movie(title="Movie without these actors")

        res = self.client.get(MOVIES_URL, {"actors": f"{actor1.id},{actor2.id}"})
        results = res.data["results"]
        titles = [movie["title"] for movie in results]

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(results), 2)
        self.assertIn(movie1.title, titles)
        self.assertIn(movie2.title, titles)


@override_settings(REST_FRAMEWORK=TEST_REST_FRAMEWORK_SETTINGS)
class MovieImageUploadTests(APITestCase):
    """Testa o upload de imagens para a API de Filmes."""
    def setUp(self):
        cache.clear()
        self.user = create_user(is_staff=True)
        self.client.force_authenticate(self.user)
        self.movie = sample_movie()

    def tearDown(self):
        """Limpa os arquivos de imagem após cada teste."""
        if self.movie.image:
            image_path = self.movie.image.path
            if os.path.exists(image_path):
                os.remove(image_path)

    def test_upload_image_to_movie(self):
        """Testa o upload de uma imagem para um filme."""
        url = image_upload_url(self.movie.id)
        with tempfile.NamedTemporaryFile(suffix=".jpg") as ntf:
            img = Image.new("RGB", (10, 10))
            img.save(ntf, format="JPEG")
            ntf.seek(0)
            res = self.client.post(url, {"image": ntf}, format="multipart")

        self.movie.refresh_from_db()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(self.movie.image)
        self.assertTrue(os.path.exists(self.movie.image.path))
