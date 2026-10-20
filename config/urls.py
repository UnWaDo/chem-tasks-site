from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from accounts import views as acc
from assignments import views_student as sv
from assignments import views_teacher as tv
from reactions import views as rv

urlpatterns = [
    path("", acc.home, name="home"),
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),

    # учитель
    path("t/", tv.dashboard, name="teacher_dashboard"),
    path("t/groups/", acc.group_list, name="group_list"),
    path("t/groups/<int:pk>/", acc.group_detail, name="group_detail"),
    path("t/groups/<int:pk>/rename/", acc.group_rename, name="group_rename"),
    path("t/groups/<int:pk>/delete/", acc.group_delete, name="group_delete"),
    path("t/groups/<int:pk>/credentials/", acc.group_credentials, name="group_credentials"),
    path("t/groups/<int:pk>/passwords/", acc.group_reset_passwords, name="group_reset_passwords"),
    path("t/students/<int:pk>/", acc.student_action, name="student_action"),

    path("t/reactions/", rv.reaction_list, name="reaction_list"),
    path("t/reactions/import/", rv.reaction_import, name="reaction_import"),
    path("t/reactions/new/", rv.reaction_edit, name="reaction_new"),
    path("t/reactions/<int:pk>/", rv.reaction_edit, name="reaction_edit"),
    path("t/reactions/<int:pk>/delete/", rv.reaction_delete, name="reaction_delete"),
    path("t/reactions/preview/", rv.reaction_live_preview, name="reaction_live_preview"),
    path("t/tags/", rv.tag_list, name="tag_list"),

    path("t/assignments/", tv.assignment_list, name="assignment_list"),
    path("t/assignments/new/", tv.assignment_edit, name="assignment_new"),
    path("t/assignments/<int:pk>/", tv.assignment_detail, name="assignment_detail"),
    path("t/assignments/<int:pk>/settings/", tv.assignment_edit, name="assignment_edit"),
    path("t/assignments/<int:pk>/add/", tv.assignment_add, name="assignment_add"),
    path("t/assignments/<int:pk>/items/<int:item_id>/", tv.item_action, name="item_action"),
    path("t/assignments/<int:pk>/check/", tv.assignment_check, name="assignment_check"),
    path("t/assignments/<int:pk>/publish/", tv.assignment_publish, name="assignment_publish"),
    path("t/assignments/<int:pk>/preview/", tv.assignment_preview, name="assignment_preview"),
    path("t/assignments/<int:pk>/results/", tv.assignment_results, name="assignment_results"),
    path("t/assignments/<int:pk>/regrade/", tv.assignment_regrade, name="assignment_regrade"),
    path("t/assignments/<int:pk>/release/", tv.assignment_release, name="assignment_release"),
    path("t/assignments/<int:pk>/copy/", tv.assignment_copy, name="assignment_copy"),
    path("t/assignments/<int:pk>/delete/", tv.assignment_delete, name="assignment_delete"),
    path("t/submissions/<int:pk>/", tv.submission_detail, name="submission_detail"),
    path("t/appeals/", tv.appeal_list, name="appeal_list"),

    # ученик
    path("s/", sv.student_home, name="student_home"),
    path("s/a/<int:pk>/", sv.assignment_view, name="student_assignment"),
    path("s/a/<int:pk>/appeal/", sv.appeal_create, name="appeal_create"),
]
