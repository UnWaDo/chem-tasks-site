from django.db import migrations


def recompute(apps, schema_editor):
    """Сигнатуры дубликатов теперь приводят градус к одному виду (t^o, t^\\circ -> t°) — пересчитываем."""
    from chem.equation import normalize_note, reaction_signature

    Reaction = apps.get_model("reactions", "Reaction")
    for r in Reaction.objects.prefetch_related("components"):
        comps = list(r.components.all())

        def keys(side):
            return [c.formula + "|" + normalize_note(c.note) for c in comps if c.side == side]

        sig = reaction_signature(keys("L"), keys("R"), r.above, r.below, r.reversible)
        if sig != r.signature:
            r.signature = sig
            r.save(update_fields=["signature"])


class Migration(migrations.Migration):
    dependencies = [("reactions", "0002_tags")]

    operations = [migrations.RunPython(recompute, migrations.RunPython.noop)]
