"""
?search= (sin acentos) y ?ordering= de las listas que alimentan las tablas del
front -- ver apps/core/filters.py.
"""
from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.employment.models import Empleado
from apps.locations.models import Nave, Ubicacion
from apps.organizations.models import OrganizationalLevel, OrganizationNode
from apps.persons.models import ContactoUrgencia, Persona
from apps.positions.models import EstatusPosicion, Posicion, Puesto
from apps.schedules.models import Catorcena
from apps.users.models import UserRole


def _nombres(response, campo="first_name"):
    return [fila[campo] for fila in response.data["results"]]


class SearchAndOrderingTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_tenant", stdout=StringIO())
        call_command("seed_organizational_levels", stdout=StringIO())
        call_command("seed_user_roles", stdout=StringIO())
        user_model = get_user_model()
        cls.gestor = user_model.objects.create_user(
            username="busqueda-gestor", email="busqueda-gestor@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.colaborador = user_model.objects.create_user(
            username="busqueda-colaborador", email="busqueda-colaborador@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="colaborador"),
        )

    def setUp(self):
        self.client.force_authenticate(user=self.gestor)

    def get(self, nombre_url, **params):
        return self.client.get(reverse(nombre_url), params)


class PersonasBusquedaYOrdenTests(SearchAndOrderingTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.perez = Persona.objects.create(
            first_name="Juan", last_name_paternal="Pérez", last_name_maternal="López",
            curp="PELJ800101HDFRPN01", personal_email="juan.perez@example.com", phone="5512345678",
        )
        cls.nunez = Persona.objects.create(first_name="José", last_name_paternal="Núñez", last_name_maternal="Ortiz")
        cls.ruiz = Persona.objects.create(first_name="Ana", last_name_paternal="Ruiz", nss="12345678901")
        cls.alvarez = Persona.objects.create(first_name="Zoe", last_name_paternal="Álvarez")

    def test_la_busqueda_ignora_acentos_y_mayusculas(self):
        for termino in ("perez", "PEREZ", "Pérez", "pÉrEz"):
            with self.subTest(termino=termino):
                self.assertEqual(_nombres(self.get("persona-list", search=termino)), ["Juan"])

    def test_la_ene_y_las_vocales_acentuadas_tambien_coinciden_sin_acento(self):
        self.assertEqual(_nombres(self.get("persona-list", search="nunez")), ["José"])
        self.assertEqual(_nombres(self.get("persona-list", search="alvarez")), ["Zoe"])
        self.assertEqual(_nombres(self.get("persona-list", search="jose")), ["José"])

    def test_varios_terminos_se_combinan_con_y(self):
        self.assertEqual(_nombres(self.get("persona-list", search="juan lopez")), ["Juan"])
        self.assertEqual(self.get("persona-list", search="juan ruiz").data["count"], 0)

    def test_busca_por_curp_correo_y_telefono(self):
        for termino in ("PELJ8001", "juan.perez@example", "5512345678"):
            with self.subTest(termino=termino):
                self.assertEqual(_nombres(self.get("persona-list", search=termino)), ["Juan"])

    def test_no_se_busca_por_campos_que_la_tabla_no_muestra(self):
        # El NSS existe en Persona, pero no es columna de la lista ni se busca.
        self.assertEqual(self.get("persona-list", search="12345678901").data["count"], 0)

    def test_sin_busqueda_o_vacia_trae_todo_y_sin_coincidencias_trae_cero(self):
        self.assertEqual(self.get("persona-list").data["count"], 4)
        self.assertEqual(self.get("persona-list", search="").data["count"], 4)
        self.assertEqual(self.get("persona-list", search="zzzz").data["count"], 0)

    def test_orden_ascendente_y_descendente(self):
        self.assertEqual(_nombres(self.get("persona-list", ordering="first_name")), ["Ana", "José", "Juan", "Zoe"])
        self.assertEqual(_nombres(self.get("persona-list", ordering="-first_name")), ["Zoe", "Juan", "José", "Ana"])

    def test_orden_por_varios_campos_desempata_con_el_segundo(self):
        for nombre in ("Bruno", "Alma", "Carla"):
            Persona.objects.create(first_name=nombre, last_name_paternal="García")
        respuesta = self.get("persona-list", search="garcia", ordering="last_name_paternal,-first_name")
        self.assertEqual(_nombres(respuesta), ["Carla", "Bruno", "Alma"])
        respuesta = self.get("persona-list", search="garcia", ordering="last_name_paternal,first_name")
        self.assertEqual(_nombres(respuesta), ["Alma", "Bruno", "Carla"])

    def test_busqueda_y_orden_se_combinan(self):
        # "a" (sin acento) coincide con Juan, Ana y Zoe Álvarez; José Núñez Ortiz no la lleva.
        respuesta = self.get("persona-list", search="a", ordering="-first_name")
        self.assertEqual(_nombres(respuesta), ["Zoe", "Juan", "Ana"])
        respuesta = self.get("persona-list", search="a", ordering="first_name")
        self.assertEqual(_nombres(respuesta), ["Ana", "Juan", "Zoe"])

    def test_la_paginacion_ordenada_por_columna_repetida_no_repite_ni_salta_filas(self):
        for numero in range(7):
            Persona.objects.create(first_name=f"Garcia{numero}", last_name_paternal="García")
        vistos = []
        pagina = 1
        while True:
            respuesta = self.get("persona-list", ordering="last_name_paternal", page=pagina, page_size=3)
            self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
            vistos += [fila["id"] for fila in respuesta.data["results"]]
            if respuesta.data["next"] is None:
                break
            pagina += 1
        total = Persona.objects.count()
        self.assertEqual(len(vistos), total)
        self.assertEqual(len(set(vistos)), total)  # sin repetidos ni faltantes

    def test_un_campo_no_permitido_para_ordenar_se_ignora_sin_error(self):
        base = [fila["id"] for fila in self.get("persona-list").data["results"]]
        for campo in ("nss", "-nss", "rfc", "birth_date", "id", "no_existe"):
            with self.subTest(campo=campo):
                respuesta = self.get("persona-list", ordering=campo)
                self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
                self.assertEqual([fila["id"] for fila in respuesta.data["results"]], base)

    def test_una_vista_sin_ordering_fields_ignora_el_orden_en_lugar_de_permitir_cualquier_campo(self):
        # DRF por defecto dejaria ordenar por cualquier campo del serializer.
        a = ContactoUrgencia.objects.create(persona=self.perez, name="Zacarías", relationship="Padre", phone="1")
        b = ContactoUrgencia.objects.create(persona=self.perez, name="Aaron", relationship="Hermano", phone="2")
        sin_orden = [fila["id"] for fila in self.get("contactourgencia-list").data["results"]]
        con_orden = [fila["id"] for fila in self.get("contactourgencia-list", ordering="name").data["results"]]
        self.assertEqual(con_orden, sin_orden)
        self.assertEqual(set(sin_orden), {str(a.pk), str(b.pk)})

    def test_un_colaborador_solo_encuentra_lo_suyo(self):
        Empleado.objects.create(persona=self.ruiz, user=self.colaborador, work_number="E-1")
        self.client.force_authenticate(user=self.colaborador)

        self.assertEqual(_nombres(self.get("persona-list", search="ruiz")), ["Ana"])
        # Buscar a otra persona no la revela, ni por nombre ni por CURP.
        self.assertEqual(self.get("persona-list", search="perez").data["count"], 0)
        self.assertEqual(self.get("persona-list", search="PELJ800101").data["count"], 0)
        # Ordenar tampoco amplia lo que se ve.
        self.assertEqual(self.get("persona-list", ordering="-first_name").data["count"], 1)


class OtrasListasBusquedaYOrdenTests(SearchAndOrderingTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        empresa = OrganizationNode.objects.create(
            level=OrganizationalLevel.objects.get(code="empresa"), code="GPA-BUSQ", name="Empresa de prueba",
        )
        cls.estatus = EstatusPosicion.objects.create(name="Vacante Activa")
        cls.tecnico = Puesto.objects.create(name="Técnico de Mantenimiento")
        cls.soldador = Puesto.objects.create(name="Soldador")
        cls.pos_tecnico = Posicion.objects.create(organization_node=empresa, estatus=cls.estatus, puesto=cls.tecnico)
        cls.pos_soldador = Posicion.objects.create(organization_node=empresa, estatus=cls.estatus, puesto=cls.soldador)

    def test_posiciones_busca_y_ordena_por_el_nombre_del_puesto(self):
        encontradas = self.get("posicion-list", search="tecnico").data["results"]
        self.assertEqual([fila["id"] for fila in encontradas], [str(self.pos_tecnico.pk)])

        desc = self.get("posicion-list", ordering="-puesto__name").data["results"]
        self.assertEqual([fila["id"] for fila in desc], [str(self.pos_tecnico.pk), str(self.pos_soldador.pk)])
        asc = self.get("posicion-list", ordering="puesto__name").data["results"]
        self.assertEqual([fila["id"] for fila in asc], [str(self.pos_soldador.pk), str(self.pos_tecnico.pk)])

    def test_posiciones_busca_por_estatus_y_por_unidad(self):
        self.assertEqual(self.get("posicion-list", search="vacante").data["count"], 2)
        self.assertEqual(self.get("posicion-list", search="empresa de prueba").data["count"], 2)

    def test_catorcenas_busca_por_numero_o_anio_aunque_sean_enteros(self):
        for numero, anio in ((1, 2026), (2, 2026), (1, 2027)):
            Catorcena.objects.create(numero=numero, anio=anio, fecha_inicio=date(anio, 1, 1), fecha_fin=date(anio, 1, 14))
        self.assertEqual(self.get("catorcena-list", search="2027").data["count"], 1)
        self.assertEqual(self.get("catorcena-list", search="2026").data["count"], 2)
        orden = self.get("catorcena-list", ordering="-anio,-numero").data["results"]
        self.assertEqual([(f["anio"], f["numero"]) for f in orden], [(2027, 1), (2026, 2), (2026, 1)])

    def test_naves_buscan_por_el_nombre_de_su_ubicacion(self):
        matriz = Ubicacion.objects.create(code="MTZ", name="Planta Matriz")
        sur = Ubicacion.objects.create(code="SUR", name="Planta Sur")
        Nave.objects.create(ubicacion=matriz, code="N1", name="Nave uno")
        Nave.objects.create(ubicacion=sur, code="N2", name="Nave dos")
        encontradas = self.get("nave-list", search="matriz").data["results"]
        self.assertEqual([fila["code"] for fila in encontradas], ["N1"])
        por_ubicacion = self.get("nave-list", ordering="-ubicacion__name").data["results"]
        self.assertEqual([fila["code"] for fila in por_ubicacion], ["N2", "N1"])

    def test_empleados_buscan_por_el_nombre_de_su_persona_sin_acentos(self):
        persona = Persona.objects.create(first_name="Luis", last_name_paternal="Hernández")
        otra = Persona.objects.create(first_name="Mara", last_name_paternal="Soto")
        Empleado.objects.create(persona=persona, work_number="E-100")
        Empleado.objects.create(persona=otra, work_number="E-200")
        por_nombre = self.get("empleado-list", search="hernandez").data["results"]
        self.assertEqual([fila["work_number"] for fila in por_nombre], ["E-100"])
        por_numero = self.get("empleado-list", search="E-200").data["results"]
        self.assertEqual([fila["work_number"] for fila in por_numero], ["E-200"])
        orden = self.get("empleado-list", ordering="-persona__last_name_paternal").data["results"]
        self.assertEqual([fila["work_number"] for fila in orden], ["E-200", "E-100"])
