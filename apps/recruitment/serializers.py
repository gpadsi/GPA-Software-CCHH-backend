from django.core.exceptions import NON_FIELD_ERRORS, ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.core.permissions import es_gestion_rrhh
from apps.persons.models import Persona
from apps.positions.models import Posicion
from apps.recruitment.models import (
    AprobacionRequisicion,
    CompetenciaConductual,
    ConformidadDescriptivo,
    DescriptivoPuesto,
    DiasPorLaborar,
    EstadoRequisicion,
    EtapaAprobacion,
    FuncionPuesto,
    HorarioACubrir,
    IndicadorDesempeno,
    RangoEdad,
    RecursoAsignado,
    Requisicion,
    RolConformidad,
    TipoContratoOfrecido,
)


def _raise_drf_validation_error(error):
    if hasattr(error, "message_dict"):
        detail = {
            api_settings.NON_FIELD_ERRORS_KEY if field == NON_FIELD_ERRORS else field: messages
            for field, messages in error.message_dict.items()
        }
    else:
        detail = {api_settings.NON_FIELD_ERRORS_KEY: error.messages}
    raise serializers.ValidationError(detail)


class FullCleanModelSerializer(serializers.ModelSerializer):
    def _save_validated_instance(self, instance):
        try:
            instance.full_clean()
        except DjangoValidationError as error:
            _raise_drf_validation_error(error)
        instance.save()
        return instance

    def create(self, validated_data):
        return self._save_validated_instance(self.Meta.model(**validated_data))

    def update(self, instance, validated_data):
        for attribute, value in validated_data.items():
            setattr(instance, attribute, value)
        return self._save_validated_instance(instance)


class TramiteAbiertoSerializer(serializers.Serializer):
    tipo = serializers.CharField(read_only=True)
    id = serializers.UUIDField(read_only=True, allow_null=True)
    estado = serializers.CharField(read_only=True, allow_null=True)


class PosicionElegibleSerializer(serializers.ModelSerializer):
    etiqueta = serializers.CharField(read_only=True)
    puesto = serializers.CharField(source="puesto.name", read_only=True, allow_null=True)
    unidad = serializers.CharField(source="organization_node.name", read_only=True)
    area = serializers.CharField(source="area.name", read_only=True, allow_null=True)
    estatus = serializers.CharField(source="estatus.name", read_only=True)
    estatus_code = serializers.CharField(source="estatus.code", read_only=True)
    ocupada = serializers.SerializerMethodField()
    tramite_abierto = serializers.SerializerMethodField()

    class Meta:
        model = Posicion
        fields = [
            "id", "etiqueta", "puesto", "unidad", "area", "estatus", "estatus_code", "ocupada", "tramite_abierto",
        ]
        read_only_fields = fields

    def get_ocupada(self, obj) -> bool:
        return obj.estatus.code.startswith(("colaborador-", "trainee-"))

    @extend_schema_field(TramiteAbiertoSerializer(allow_null=True))
    def get_tramite_abierto(self, obj):
        if not obj.tiene_tramite_abierto:
            return None
        para = self.context["request"].query_params["para"]
        return {
            "tipo": para,
            "id": str(obj.tramite_id) if obj.tramite_id is not None else None,
            "estado": obj.tramite_estado if para == "requisicion" else "Borrador",
        }


class EstadoRequisicionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoRequisicion
        fields = ["id", "code", "name", "is_active", "es_terminal"]
        read_only_fields = fields


class EtapaAprobacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EtapaAprobacion
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class TipoContratoOfrecidoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoContratoOfrecido
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class HorarioACubrirSerializer(serializers.ModelSerializer):
    class Meta:
        model = HorarioACubrir
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class AprobacionRequisicionSerializer(FullCleanModelSerializer):
    class Meta:
        model = AprobacionRequisicion
        fields = ["id", "requisicion", "etapa", "fecha", "usuario", "nombre_manual"]
        read_only_fields = ["id"]


# Los únicos estados que el solicitante (cualquier usuario autenticado) puede
# poner por sí mismo: empezar en Borrador y mandarla a autorización. Del resto
# (Autorizada, En Reclutamiento, Cubierta...) se encarga Capital Humano -- el
# permiso de crear es abierto a propósito, y la legitimidad la da el flujo de
# aprobación, así que el solicitante no debe poder saltárselo autorizándose.
ESTADOS_QUE_ELIGE_EL_SOLICITANTE = ("borrador", "pendiente-de-autorizacion")


class RequisicionSerializer(FullCleanModelSerializer):
    # Opcional: si no se manda, empieza en Borrador.
    estado = serializers.PrimaryKeyRelatedField(queryset=EstadoRequisicion.objects.all(), required=False)
    aprobaciones = AprobacionRequisicionSerializer(many=True, read_only=True)
    # Solo lectura. La etiqueta evita que cada fila de una lista tenga que ir a
    # buscar el nombre de su Posición; `creado_por` deja al front saber si la
    # cuenta es la dueña (puede editarla) sin repetir esa regla; `solicitante`
    # es null en las requisiciones importadas, que no las levantó nadie.
    posicion_etiqueta = serializers.CharField(source="posicion.etiqueta", read_only=True)
    creado_por = serializers.PrimaryKeyRelatedField(source="created_by", read_only=True)
    solicitante = serializers.SerializerMethodField()

    class Meta:
        model = Requisicion
        fields = [
            "id", "posicion", "posicion_etiqueta", "tipo", "estado", "creado_por", "solicitante",
            "fecha_solicitud", "fecha_a_cubrir_vacante", "fecha_entrega_a_capital_humano",
            "area_solicitante", "justificacion",
            "horario_a_cubrir", "idiomas_requeridos", "disposicion_viajar",
            "nivel_tabulador", "sueldo_mensual_compuesto", "sueldo_mensual_bruto", "sueldo_mensual_neto",
            "tipo_contrato_ofrecido",
            "motivo_suspension", "fecha_suspension", "autorizado_por_suspension",
            "aprobaciones",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        es_gestor = request is not None and es_gestion_rrhh(request.user)
        estado = attrs.get("estado")
        if self.instance is None and estado is None:
            estado = EstadoRequisicion.objects.filter(code=ESTADOS_QUE_ELIGE_EL_SOLICITANTE[0]).first()
            if estado is None:
                raise serializers.ValidationError({"estado": "Falta el estado inicial «Borrador» en el catálogo."})
            attrs["estado"] = estado
        cambia = estado is not None and (self.instance is None or estado.pk != self.instance.estado_id)
        if cambia and not es_gestor and estado.code not in ESTADOS_QUE_ELIGE_EL_SOLICITANTE:
            raise serializers.ValidationError({
                "estado": "Solo Capital Humano puede poner una requisición en este estado: "
                          "tú puedes dejarla en Borrador o mandarla a autorización."
            })
        return attrs

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_solicitante(self, requisicion):
        usuario = requisicion.created_by
        return (usuario.get_full_name() or usuario.username) if usuario else None


# ---------------------------------------------------------------------------
# Descriptivo de Puesto
# ---------------------------------------------------------------------------

class RangoEdadSerializer(serializers.ModelSerializer):
    class Meta:
        model = RangoEdad
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class DiasPorLaborarSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiasPorLaborar
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class CompetenciaConductualSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompetenciaConductual
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class RecursoAsignadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecursoAsignado
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class RolConformidadSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolConformidad
        fields = ["id", "code", "name", "is_active", "requiere_persona"]
        read_only_fields = fields


class FuncionPuestoSerializer(serializers.ModelSerializer):
    # El número lo da la posición en la lista que manda el cliente (1, 2,
    # 3...): así nunca hay huecos ni repetidos que validar.
    class Meta:
        model = FuncionPuesto
        fields = ["orden", "texto"]
        read_only_fields = ["orden"]


class IndicadorDesempenoSerializer(serializers.ModelSerializer):
    class Meta:
        model = IndicadorDesempeno
        fields = ["orden", "texto"]
        read_only_fields = ["orden"]


class ConformidadDescriptivoSerializer(FullCleanModelSerializer):
    # Declarado a mano a propósito: DRF vuelve obligatorio (required=True) todo
    # campo que aparece en una UniqueConstraint, y aquí `persona` es opcional
    # (solo el rol Colaborador la exige, y eso lo valida el modelo).
    persona = serializers.PrimaryKeyRelatedField(queryset=Persona.objects.all(), required=False, allow_null=True)
    # Solo lectura: para mostrar a quién pertenece sin otra consulta por fila.
    persona_nombre = serializers.SerializerMethodField()

    class Meta:
        model = ConformidadDescriptivo
        fields = ["id", "descriptivo", "rol", "persona", "persona_nombre", "fecha", "usuario", "nombre_manual"]
        read_only_fields = ["id"]
        # DRF arma un UniqueTogetherValidator por cada UniqueConstraint
        # IGNORANDO su condición: el de (descriptivo, rol) bloquearía que dos
        # personas distintas den su conformidad como Colaborador sobre la
        # misma versión. full_clean() del modelo sí respeta la condición
        # (persona nula / no borrado) y devuelve el mismo error, así que la
        # unicidad se valida ahí.
        validators = []

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_persona_nombre(self, conformidad):
        return str(conformidad.persona) if conformidad.persona_id else None

    def validate(self, attrs):
        # Una conformidad pertenece a UNA versión: moverla a otra
        # desvirtuaría "firmó esta versión".
        if self.instance and "descriptivo" in attrs and attrs["descriptivo"].pk != self.instance.descriptivo_id:
            raise serializers.ValidationError({"descriptivo": "No se puede mover una conformidad a otra versión."})
        return attrs


class DescriptivoPuestoSerializer(FullCleanModelSerializer):
    """
    Funciones e indicadores se mandan como lista completa (`[{"texto": ...}]`)
    y REEMPLAZAN la anterior; omitir la clave los deja como están. Las
    casillas (competencias/recursos) son listas de ids de catálogo con la
    misma regla. Todo esto solo aplica a un borrador: contra una versión
    congelada la validación del modelo lo rechaza ANTES de tocar nada.
    """
    funciones = FuncionPuestoSerializer(many=True, required=False)
    indicadores = IndicadorDesempenoSerializer(many=True, required=False)
    competencias = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=CompetenciaConductual.objects.all(),
    )
    recursos = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=RecursoAsignado.objects.all())
    conformidades = ConformidadDescriptivoSerializer(many=True, read_only=True)
    esta_congelado = serializers.BooleanField(read_only=True)

    posicion_etiqueta = serializers.CharField(source="posicion.etiqueta", read_only=True)

    class Meta:
        model = DescriptivoPuesto
        fields = [
            "id", "posicion", "posicion_etiqueta", "version", "congelado_en", "esta_congelado",
            "nombre_puesto", "empresa", "area_departamento", "reporta_a", "supervisa_a", "fecha_elaboracion",
            "edad", "edad_otro", "disponibilidad_viajar",
            "dias_por_laborar", "dias_por_laborar_otro", "horario", "horario_otro",
            "proposito", "decisiones_operativas", "decisiones_funcionales", "decisiones_estrategicas",
            "relaciones_internas", "relaciones_externas",
            "escolaridad_minima", "experiencia_requerida", "idiomas", "competencias_tecnicas",
            "competencias", "competencias_otras", "recursos", "recursos_otro",
            "funciones", "indicadores", "conformidades",
        ]
        read_only_fields = ["id", "version", "congelado_en"]
        # La unicidad (posición, versión) y "un solo borrador" las valida el
        # full_clean() del modelo -- el validador automático de DRF no respeta
        # las condiciones de las UniqueConstraint (ver ConformidadDescriptivoSerializer).
        validators = []

    def validate(self, attrs):
        # Cambiar la Posición de una versión ya creada rompería la numeración
        # (v1, v2... son por Posición): se crea otro Descriptivo en su lugar.
        if self.instance and "posicion" in attrs and attrs["posicion"].pk != self.instance.posicion_id:
            raise serializers.ValidationError({"posicion": "No se puede cambiar la Posición de un Descriptivo."})
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        # Quién dio su conformidad (personas concretas) no es un dato que
        # deba ver cualquier Colaborador -- mismo criterio que no exponer un
        # directorio de compañeros.
        if request is None or not es_gestion_rrhh(request.user):
            data.pop("conformidades", None)
        return data

    def _guardar_listas(self, descriptivo, funciones, indicadores, competencias, recursos):
        usuario = self.context["request"].user
        for modelo, relacion, elementos in (
            (FuncionPuesto, descriptivo.funciones, funciones),
            (IndicadorDesempeno, descriptivo.indicadores, indicadores),
        ):
            if elementos is None:
                continue
            relacion.all().delete()
            for numero, elemento in enumerate(elementos, start=1):
                modelo.objects.create(
                    descriptivo=descriptivo, orden=numero, texto=elemento["texto"],
                    created_by=usuario, updated_by=usuario,
                )
        if competencias is not None:
            descriptivo.competencias.set(competencias)
        if recursos is not None:
            descriptivo.recursos.set(recursos)

    def _separar_listas(self, validated_data):
        return tuple(validated_data.pop(clave, None) for clave in ("funciones", "indicadores", "competencias", "recursos"))

    def create(self, validated_data):
        listas = self._separar_listas(validated_data)
        with transaction.atomic():
            descriptivo = super().create(validated_data)
            self._guardar_listas(descriptivo, *listas)
        return descriptivo

    def update(self, instance, validated_data):
        listas = self._separar_listas(validated_data)
        with transaction.atomic():
            # full_clean() corre primero y rechaza una versión congelada
            # antes de que se toque cualquier lista o casilla.
            descriptivo = super().update(instance, validated_data)
            self._guardar_listas(descriptivo, *listas)
        return descriptivo


class CrearBorradorSerializer(serializers.Serializer):
    posicion = serializers.PrimaryKeyRelatedField(queryset=Posicion.objects.all())
