from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import StudentGroup
from reactions.models import Reaction

INHERIT_CHOICES = [(None, "как в задании"), (True, "да"), (False, "нет")]


class Assignment(models.Model):
    RESULTS_IMMEDIATE = "immediate"
    RESULTS_DATE = "date"
    RESULTS_MANUAL = "manual"
    RESULTS_CHOICES = [
        (RESULTS_IMMEDIATE, "сразу после сдачи"),
        (RESULTS_DATE, "с указанной даты"),
        (RESULTS_MANUAL, "после подтверждения учителем"),
    ]

    title = models.CharField("название", max_length=200)
    description = models.TextField("инструкция для учеников", blank=True)
    groups = models.ManyToManyField(StudentGroup, blank=True, related_name="assignments", verbose_name="классы")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    is_published = models.BooleanField("опубликовано", default=False)
    opens_at = models.DateTimeField("доступно с", null=True, blank=True)
    due_at = models.DateTimeField("сдать до", null=True, blank=True)
    allow_late = models.BooleanField("принимать после срока", default=False)

    results_mode = models.CharField("показ результатов", max_length=10, choices=RESULTS_CHOICES,
                                    default=RESULTS_IMMEDIATE)
    results_date = models.DateTimeField("дата показа результатов", null=True, blank=True)
    results_released = models.BooleanField("результаты открыты учителем", default=False)
    show_correct_answers = models.BooleanField("показывать правильные ответы в результатах", default=False)
    allow_appeals = models.BooleanField("разрешить апелляции", default=True)
    partial_credit = models.BooleanField("½ балла за верные вещества с неверными коэффициентами", default=True)

    # настройки показа по умолчанию (могут переопределяться в каждой реакции задания)
    show_reactants = models.BooleanField("показывать реагенты", default=True)
    show_products = models.BooleanField("показывать продукты", default=False)
    show_count = models.BooleanField("показывать количество скрытых веществ", default=False)
    hide_water = models.BooleanField("прятать воду", default=False)

    checked_at = models.DateTimeField("проверка на неоднозначность", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "задание"
        verbose_name_plural = "задания"

    def __str__(self):
        return self.title

    def is_open(self, now=None) -> bool:
        now = now or timezone.now()
        return self.is_published and (self.opens_at is None or self.opens_at <= now)

    def accepts_submissions(self, now=None) -> bool:
        now = now or timezone.now()
        return self.is_open(now) and (self.due_at is None or now <= self.due_at or self.allow_late)

    def is_late(self, now=None) -> bool:
        now = now or timezone.now()
        return self.due_at is not None and now > self.due_at

    @property
    def max_score(self) -> int:
        return self.items.count()


class AssignmentItem(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="items")
    reaction = models.ForeignKey(Reaction, on_delete=models.PROTECT, related_name="assignment_items")
    position = models.PositiveIntegerField(default=0)

    show_reactants = models.BooleanField(null=True, blank=True)
    show_products = models.BooleanField(null=True, blank=True)
    show_count = models.BooleanField(null=True, blank=True)
    hide_water = models.BooleanField(null=True, blank=True)
    # {"L:HNO3": true, "R:H2O": false} — явный показ/скрытие отдельных веществ
    overrides = models.JSONField(default=dict, blank=True)

    alternatives = models.ManyToManyField(Reaction, blank=True, related_name="+",
                                          verbose_name="тоже считать правильными")
    dismissed = models.ManyToManyField(Reaction, blank=True, related_name="+",
                                       verbose_name="не считать правильными")

    class Meta:
        ordering = ["position", "id"]
        unique_together = [("assignment", "reaction")]

    def __str__(self):
        return f"{self.assignment} — {self.reaction}"

    def effective(self, name: str) -> bool:
        own = getattr(self, name)
        return getattr(self.assignment, name) if own is None else own


class Submission(models.Model):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    STATUS_CHOICES = [(DRAFT, "черновик"), (SUBMITTED, "сдано")]

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)
    max_score = models.FloatField(null=True, blank=True)
    released = models.BooleanField("результат открыт учителем", default=False)

    class Meta:
        ordering = ["-submitted_at"]
        unique_together = [("assignment", "student")]

    def __str__(self):
        return f"{self.student} — {self.assignment}"

    @property
    def is_submitted(self):
        return self.status == self.SUBMITTED

    @property
    def is_late(self):
        a = self.assignment
        return bool(self.submitted_at and a.due_at and self.submitted_at > a.due_at)

    @property
    def percent(self):
        if self.score is None or not self.max_score:
            return None
        return round(100 * self.score / self.max_score)

    def results_visible(self, now=None) -> bool:
        if not self.is_submitted or self.score is None:
            return False
        a = self.assignment
        now = now or timezone.now()
        if a.results_mode == Assignment.RESULTS_IMMEDIATE:
            return True
        if a.results_mode == Assignment.RESULTS_DATE:
            return a.results_date is not None and now >= a.results_date or self.released
        return a.results_released or self.released


class Answer(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="answers")
    item = models.ForeignKey(AssignmentItem, on_delete=models.CASCADE, related_name="answers")
    data = models.JSONField(default=dict, blank=True)   # {"L": [{"c": "2", "f": "H2"}], "R": [...]}
    auto_score = models.FloatField(null=True, blank=True)
    verdict = models.CharField(max_length=10, blank=True)
    feedback = models.TextField(blank=True)
    matched_reaction = models.ForeignKey(Reaction, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    manual_score = models.FloatField("оценка учителя", null=True, blank=True)
    manual_comment = models.TextField("комментарий учителя", blank=True)

    class Meta:
        unique_together = [("submission", "item")]
        ordering = ["item__position", "item_id"]

    @property
    def score(self):
        return self.manual_score if self.manual_score is not None else (self.auto_score or 0)

    @property
    def final_verdict(self):
        if self.manual_score is None:
            return self.verdict or "empty"
        if self.manual_score >= 1:
            return "correct"
        return "partial" if self.manual_score > 0 else "wrong"


class Appeal(models.Model):
    OPEN, ACCEPTED, REJECTED = "open", "accepted", "rejected"
    STATUS_CHOICES = [(OPEN, "на рассмотрении"), (ACCEPTED, "удовлетворена"), (REJECTED, "отклонена")]

    answer = models.ForeignKey(Answer, on_delete=models.CASCADE, related_name="appeals")
    text = models.TextField("текст апелляции")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=OPEN)
    response = models.TextField("ответ учителя", blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
