def teacher_badges(request):
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_staff):
        return {}
    from .models import Appeal
    return {"open_appeals_count": Appeal.objects.filter(status=Appeal.OPEN).count()}
