from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils.safestring import mark_safe

from chem.equation import Equation, arrow_html, equation_text, normalize_note, reaction_signature, term_html

SIDES = [("L", "реагенты"), ("R", "продукты")]


class Tag(models.Model):
    name = models.CharField("название", max_length=60, unique=True)

    class Meta:
        ordering = [Lower("name")]
        verbose_name = "тэг"
        verbose_name_plural = "тэги"

    def __str__(self):
        return self.name


class Reaction(models.Model):
    tags = models.ManyToManyField(Tag, blank=True, related_name="reactions", verbose_name="тэги")
    above = models.CharField("условия над стрелкой", max_length=200, blank=True)
    below = models.CharField("условия под стрелкой", max_length=200, blank=True)
    reversible = models.BooleanField("обратимая", default=False)
    signature = models.CharField(max_length=1000, db_index=True, editable=False)
    comment = models.TextField("комментарий", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "реакция"
        verbose_name_plural = "реакции"

    def __str__(self):
        return self.text()

    # ---- составные части (работают с prefetch_related("components"))
    def _components(self):
        return list(self.components.all())

    def left(self):
        return [c for c in self._components() if c.side == "L"]

    def right(self):
        return [c for c in self._components() if c.side == "R"]

    def side(self, side):
        return self.left() if side == "L" else self.right()

    def text(self) -> str:
        def items(cs):
            return [(c.coef, c.formula, c.note, c.mark) for c in cs]
        return equation_text(items(self.left()), items(self.right()), self.above, self.below, self.reversible)

    def html(self, show_coefs=True):
        def side(cs):
            return '<span class="plus"> + </span>'.join(
                f'<span class="term">{term_html(c.coef, c.formula, c.note, c.mark, show_coefs)}</span>' for c in cs)
        return mark_safe(f'<span class="eq">{side(self.left())}{arrow_html(self.above, self.below, self.reversible)}'
                         f'{side(self.right())}</span>')

    def arrow_html(self):
        return mark_safe(arrow_html(self.above, self.below, self.reversible))

    def reference(self):
        """Эталон для проверки: ({формула: коэф} реагентов, {формула: коэф} продуктов)."""
        return ({c.formula: c.coef for c in self.left()}, {c.formula: c.coef for c in self.right()})

    def compute_signature(self) -> str:
        def keys(cs):
            return [c.formula + "|" + normalize_note(c.note) for c in cs]
        return reaction_signature(keys(self.left()), keys(self.right()), self.above, self.below, self.reversible)

    @transaction.atomic
    def set_equation(self, eq: Equation, coefs=None):
        """Сохраняет реакцию по разобранному уравнению (с заменой коэффициентов при необходимости)."""
        if coefs is not None:
            eq = eq.with_coefficients(coefs)
        self.above, self.below, self.reversible = eq.above, eq.below, eq.reversible
        self.signature = eq.signature()
        self.save()
        self.components.all().delete()
        Component.objects.bulk_create(
            [Component(reaction=self, side="L", position=i, coef=t.coef or 1, formula=t.formula.text,
                       note=t.note, mark=t.mark) for i, t in enumerate(eq.left)]
            + [Component(reaction=self, side="R", position=i, coef=t.coef or 1, formula=t.formula.text,
                         note=t.note, mark=t.mark) for i, t in enumerate(eq.right)]
        )
        if hasattr(self, "_prefetched_objects_cache"):
            self._prefetched_objects_cache.pop("components", None)
        return self


class Component(models.Model):
    reaction = models.ForeignKey(Reaction, on_delete=models.CASCADE, related_name="components")
    side = models.CharField(max_length=1, choices=SIDES)
    position = models.PositiveSmallIntegerField(default=0)
    coef = models.PositiveIntegerField(default=1)
    formula = models.CharField(max_length=120, db_index=True)
    note = models.CharField("пояснение", max_length=120, blank=True)
    mark = models.CharField(max_length=4, blank=True)

    class Meta:
        ordering = ["side", "position"]

    def __str__(self):
        return self.formula

    @property
    def key(self) -> str:
        """Ключ вещества в настройках задания."""
        return f"{self.side}:{self.formula}"

    @property
    def is_water(self) -> bool:
        return self.formula == "H2O"

    def html(self, show_coef=False):
        return mark_safe(term_html(self.coef, self.formula, self.note, self.mark, show_coef))
