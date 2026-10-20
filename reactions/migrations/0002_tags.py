from django.db import migrations, models


def topics_to_tags(apps, schema_editor):
    Reaction = apps.get_model("reactions", "Reaction")
    Tag = apps.get_model("reactions", "Tag")
    for reaction in Reaction.objects.exclude(topic=""):
        name = reaction.topic.strip()[:60]
        # сравнение без учёта регистра на стороне Python (работает и для кириллицы)
        tag = next((t for t in Tag.objects.all() if t.name.lower() == name.lower()), None)
        tag = tag or Tag.objects.create(name=name)
        reaction.tags.add(tag)


def tags_to_topics(apps, schema_editor):
    Reaction = apps.get_model("reactions", "Reaction")
    for reaction in Reaction.objects.prefetch_related("tags"):
        names = [t.name for t in reaction.tags.all()]
        if names:
            reaction.topic = ", ".join(names)[:200]
            reaction.save(update_fields=["topic"])


class Migration(migrations.Migration):
    dependencies = [("reactions", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Tag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, unique=True, verbose_name="название")),
            ],
            options={"ordering": ["name"], "verbose_name": "тэг", "verbose_name_plural": "тэги"},
        ),
        migrations.AddField(
            model_name="reaction",
            name="tags",
            field=models.ManyToManyField(blank=True, related_name="reactions", to="reactions.tag", verbose_name="тэги"),
        ),
        migrations.RunPython(topics_to_tags, tags_to_topics),
        migrations.RemoveField(model_name="reaction", name="topic"),
    ]
