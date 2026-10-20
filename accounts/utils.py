import re
import secrets

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Student, StudentGroup

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
# без похожих символов (l/1/I, O/0), чтобы пароль легко было переписать с листочка
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def is_teacher(user) -> bool:
    return user.is_authenticated and user.is_staff


def translit(text: str) -> str:
    out = "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())
    return re.sub(r"[^a-z0-9]", "", out)


def generate_password(length: int = 8) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def make_login(full_name: str, prefix: str = "") -> str:
    """«Иванов Иван Петрович» -> «ivanov.i» (или prefix + «ivanov.i»), с числом при совпадении."""
    parts = full_name.split()
    base = translit(parts[0]) if parts else ""
    if len(parts) > 1 and translit(parts[1]):
        base += "." + translit(parts[1])[0]
    base = (translit(prefix) + "." if prefix and translit(prefix) else "") + (base or "student")
    User = get_user_model()
    login, n = base, 1
    while User.objects.filter(username=login).exists():
        n += 1
        login = f"{base}{n}"
    return login


@transaction.atomic
def create_students(group: StudentGroup, names: list[str], prefix: str = "") -> list[dict]:
    """Создаёт учеников и возвращает выданные данные для входа (пароли нигде не хранятся в открытом виде)."""
    User = get_user_model()
    created = []
    for name in names:
        name = " ".join(name.split())
        if not name:
            continue
        login = make_login(name, prefix)
        password = generate_password()
        parts = name.split()
        user = User.objects.create_user(
            username=login, password=password,
            last_name=parts[0][:150], first_name=" ".join(parts[1:])[:150],
        )
        Student.objects.create(user=user, group=group, full_name=name)
        created.append({"name": name, "login": login, "password": password, "group": group.name})
    return created


@transaction.atomic
def reset_passwords(students) -> list[dict]:
    out = []
    for st in students:
        password = generate_password()
        st.user.set_password(password)
        st.user.save(update_fields=["password"])
        out.append({"name": st.full_name, "login": st.user.username, "password": password, "group": st.group.name})
    return out
