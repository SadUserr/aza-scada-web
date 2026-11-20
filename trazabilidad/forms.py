from django import forms
from cuentas.models import Rol, Usuario
from .models import Lote, Observacion, Receta


class RecetaForm(forms.ModelForm):
    codigo_letra = forms.CharField(max_length=6, required=False, label="Código / Letra de receta")

    class Meta:
        model = Receta
        fields = ["codigo_letra", "nombre", "espesor_mm", "material", "min_tol", "max_tol"]

    def clean_codigo_letra(self):
        val = (self.cleaned_data.get("codigo_letra") or "").strip().upper()
        if not val:
            return (self.instance.codigo_letra if self.instance and self.instance.pk else "A") or "A"
        return val


class LoteForm(forms.ModelForm):
    codigo = forms.CharField(max_length=50, required=False, label="Código del lote")
    receta = forms.ModelChoiceField(Receta.objects.none(), required=True, empty_label=None)
    operador_inicio = forms.ModelChoiceField(
        Usuario.objects.none(), required=False, empty_label="Sin asignar (lo inicia el operador en línea)"
    )

    class Meta:
        model = Lote
        fields = ["codigo", "receta", "operador_inicio", "cantidad"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["receta"].queryset = Receta.objects.filter(activo=True).order_by("codigo_letra", "nombre")
        self.fields["operador_inicio"].queryset = Usuario.objects.filter(
            is_active=True, rol__nombre=Rol.OPERADOR
        ).order_by("username")

    def clean_codigo(self):
        c = (self.cleaned_data.get("codigo") or "").strip()
        if c and Lote.objects.filter(codigo=c).exists():
            raise forms.ValidationError("Ya existe un Lote con este código.")
        return c

    def save(self, commit=True):
        inst = super().save(commit=False)
        if not inst.codigo:
            inst.codigo = Lote.generar_codigo(inst.receta)
        if inst.operador_inicio and not inst.operador_activo:
            inst.operador_activo = inst.operador_inicio
        if commit:
            inst.save()
        return inst


class UsuarioForm(forms.Form):
    nombre_completo = forms.CharField(max_length=150)
    username = forms.CharField(max_length=100)
    rol = forms.ModelChoiceField(Rol.objects.all(), empty_label=None)

    def clean_username(self):
        u = self.cleaned_data["username"].strip()
        if Usuario.objects.filter(username=u).exists():
            raise forms.ValidationError("El nombre de usuario ya existe.")
        return u


class ObservacionForm(forms.ModelForm):
    descripcion = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))

    class Meta:
        model = Observacion
        fields = ["tipo", "descripcion"]

    def clean_descripcion(self):
        d = self.cleaned_data["descripcion"].strip()
        if not d:
            raise forms.ValidationError("La descripción no puede estar vacía.")
        return d


class TokenForm(forms.Form):
    nombre = forms.CharField(max_length=100, label="Estación de captura (ej. Cámara línea 1, Nodo Jetson)")
