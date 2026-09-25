from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from apps.imports.models import RawValueAlias
from apps.imports.normalize import normalize_text, resolve_against_catalog
from apps.persons.models import Genero


class NormalizeTextTests(TestCase):
    def test_none_becomes_empty_string(self):
        self.assertEqual(normalize_text(None), "")

    def test_uppercases_and_strips_extra_whitespace(self):
        self.assertEqual(normalize_text("  matriz  "), "MATRIZ")

    def test_strips_accents(self):
        self.assertEqual(normalize_text("Ingeniería"), "INGENIERIA")

    def test_punctuation_becomes_whitespace_and_collapses(self):
        self.assertEqual(normalize_text("ING."), "ING")
        self.assertEqual(normalize_text("Auxiliar, de Producción"), "AUXILIAR DE PRODUCCION")

    def test_inserts_space_between_letters_and_digits_even_without_domain(self):
        self.assertEqual(normalize_text("N1"), "N 1")

    def test_domain_synonym_substitution_applies_per_token(self):
        self.assertEqual(normalize_text("AUX", domain="puesto"), "AUXILIAR")
        self.assertEqual(normalize_text("N1", domain="nave"), "NAVE 1")

    def test_synonyms_are_scoped_to_their_own_domain(self):
        # "N" solo se expande a "NAVE" en el dominio "nave" — en "puesto" no
        # existe ese sinónimo, así que se queda tal cual.
        self.assertEqual(normalize_text("N1", domain="puesto"), "N 1")

    def test_domain_word_merge_replaces_the_whole_normalized_phrase(self):
        self.assertEqual(normalize_text("Operador de Soldador", domain="puesto"), "OPERADOR DE SOLDADURA")

    def test_unmapped_value_in_a_domain_is_returned_unchanged(self):
        self.assertEqual(normalize_text("Valor Sin Mapear", domain="puesto"), "VALOR SIN MAPEAR")


class ResolveAgainstCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.masculino = Genero.objects.create(name="Masculino")

    def test_resolves_by_exact_normalized_name_match(self):
        obj, normalized = resolve_against_catalog("  masculino  ", Genero.objects.all(), "genero", RawValueAlias)
        self.assertEqual(obj, self.masculino)
        self.assertEqual(normalized, "MASCULINO")

    def test_returns_none_and_the_normalized_value_when_nothing_matches(self):
        obj, normalized = resolve_against_catalog("Otro Valor", Genero.objects.all(), "genero", RawValueAlias)
        self.assertIsNone(obj)
        self.assertEqual(normalized, "OTRO VALOR")

    def test_never_creates_anything_when_unresolved(self):
        resolve_against_catalog("Valor Inventado", Genero.objects.all(), "genero", RawValueAlias)
        self.assertFalse(Genero.objects.filter(name="Valor Inventado").exists())

    def test_a_confirmed_alias_resolves_even_when_the_text_does_not_match_the_name(self):
        content_type = ContentType.objects.get_for_model(Genero)
        RawValueAlias.objects.create(
            domain="genero", raw_value="MASC", raw_value_original="Masc",
            content_type=content_type, object_id=str(self.masculino.pk),
        )

        obj, normalized = resolve_against_catalog("Masc", Genero.objects.all(), "genero", RawValueAlias)
        self.assertEqual(obj, self.masculino)
        self.assertEqual(normalized, "MASC")
