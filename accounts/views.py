from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Student, StudentGroup
from .utils import create_students, is_teacher, reset_passwords

teacher_required = user_passes_test(is_teacher, login_url="login")


@login_required
def home(request):
    if is_teacher(request.user):
        return redirect("teacher_dashboard")
    return redirect("student_home")


class GroupForm(forms.ModelForm):
    class Meta:
        model = StudentGroup
        fields = ["name"]


class AddStudentsForm(forms.Form):
    names = forms.CharField(
        label="Ученики (по одному на строке: Фамилия Имя)",
        widget=forms.Textarea(attrs={"rows": 10, "placeholder": "Иванов Иван\nПетрова Мария"}),
    )
    prefix = forms.CharField(label="Префикс логина (необязательно, например 10a)", required=False, max_length=20)


def _show_credentials(request, group, creds, title):
    """Пароли показываются один раз: кладём в сессию и перенаправляем (обновление страницы не создаст учеников заново)."""
    request.session["credentials"] = {"group": group.pk, "creds": creds, "title": title}
    return redirect("group_credentials", group.pk)


@teacher_required
def group_credentials(request, pk):
    group = get_object_or_404(StudentGroup, pk=pk)
    data = request.session.pop("credentials", None)
    if not data or data.get("group") != group.pk:
        messages.info(request, "Пароли показываются только один раз. При необходимости выдайте новые.")
        return redirect("group_detail", pk)
    return render(request, "teacher/credentials.html", {"creds": data["creds"], "group": group, "title": data["title"]})


@teacher_required
def group_list(request):
    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        g = form.save()
        messages.success(request, f"Класс «{g.name}» создан. Добавьте учеников.")
        return redirect("group_detail", g.pk)
    groups = StudentGroup.objects.all()
    return render(request, "teacher/group_list.html", {"groups": groups, "form": form})


@teacher_required
def group_detail(request, pk):
    group = get_object_or_404(StudentGroup, pk=pk)
    form = AddStudentsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        names = form.cleaned_data["names"].splitlines()
        creds = create_students(group, names, form.cleaned_data["prefix"])
        return _show_credentials(request, group, creds, f"Новые ученики — {group.name}")
    rename = GroupForm(instance=group, prefix="rename")
    students = group.students.select_related("user")
    return render(request, "teacher/group_detail.html", {
        "group": group, "form": form, "students": students, "rename": rename,
        "other_groups": StudentGroup.objects.exclude(pk=group.pk)})


@teacher_required
@require_POST
def group_rename(request, pk):
    group = get_object_or_404(StudentGroup, pk=pk)
    form = GroupForm(request.POST, instance=group, prefix="rename")
    if form.is_valid():
        form.save()
        messages.success(request, "Название изменено.")
    else:
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("group_detail", pk)


@teacher_required
@require_POST
def group_delete(request, pk):
    group = get_object_or_404(StudentGroup, pk=pk)
    for st in group.students.select_related("user"):
        st.user.delete()
    group.delete()
    messages.success(request, f"Класс «{group.name}» и его ученики удалены.")
    return redirect("group_list")


@teacher_required
@require_POST
def group_reset_passwords(request, pk):
    group = get_object_or_404(StudentGroup, pk=pk)
    ids = request.POST.getlist("student")
    students = group.students.select_related("user", "group")
    if ids:
        students = students.filter(pk__in=ids)
    creds = reset_passwords(students)
    return _show_credentials(request, group, creds, f"Новые пароли — {group.name}")


@teacher_required
@require_POST
def student_action(request, pk):
    st = get_object_or_404(Student.objects.select_related("user", "group"), pk=pk)
    action = request.POST.get("action")
    if action == "reset":
        creds = reset_passwords([st])
        return _show_credentials(request, st.group, creds, f"Новый пароль — {st.full_name}")
    if action == "toggle":
        st.user.is_active = not st.user.is_active
        st.user.save(update_fields=["is_active"])
        messages.success(request, f"{st.full_name}: вход {'разрешён' if st.user.is_active else 'заблокирован'}.")
    elif action == "move":
        target = get_object_or_404(StudentGroup, pk=request.POST.get("group"))
        st.group = target
        st.save(update_fields=["group"])
        messages.success(request, f"{st.full_name}: перевод в «{target.name}» выполнен.")
    elif action == "set_password":
        password = request.POST.get("password", "")
        try:
            validate_password(password, st.user)
        except ValidationError as e:
            messages.error(request, f"{st.full_name}: пароль не изменён — " + " ".join(e.messages))
        else:
            st.user.set_password(password)
            st.user.save(update_fields=["password"])
            messages.success(request, f"{st.full_name}: пароль изменён.")
    elif action == "delete":
        st.user.delete()
        messages.success(request, f"Ученик {st.full_name} удалён вместе с его работами.")
    return redirect("group_detail", st.group_id)
