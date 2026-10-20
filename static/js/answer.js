// Форма ответа ученика: добавление/удаление веществ, отрисовка уравнения, защита от потери ввода.
(function () {
  var form = document.getElementById("answer-form");
  if (!form) return;
  var dirty = false;

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // Строка уравнения под полями ввода: то же, что ввёл ученик, с индексами и зарядами
  function renderTask(task) {
    task.querySelectorAll(".side").forEach(function (side) {
      var terms = Array.from(side.querySelectorAll(".trow")).map(function (row) {
        var coef = row.querySelector("input.coef").value.trim();
        var input = row.querySelector("input.f") || row.querySelector('input[type=hidden][name$="_f"]');
        var f = input.value.trim();
        var html = coef && coef !== "1" ? '<span class="coef">' + esc(coef) + "</span>" : "";
        if (!f) return '<span class="term">' + html + '<span class="term blank">?</span></span>';
        html += '<span class="formula">' + window.formulaHtml(f) + "</span>";
        if (row.dataset.mark) html += '<span class="mark">' + esc(row.dataset.mark) + "</span>";
        if (row.dataset.noteHtml) html += '<span class="note">(' + row.dataset.noteHtml + ")</span>";  // уже экранировано сервером
        return '<span class="term">' + html + "</span>";
      });
      var target = task.querySelector('[data-render="' + side.getAttribute("data-side") + '"]');
      target.innerHTML = terms.join('<span class="plus"> + </span>') || '<span class="term blank">?</span>';
    });
  }

  function newRow(side) {
    var item = side.getAttribute("data-item");
    var code = side.getAttribute("data-side");
    var idx = parseInt(side.getAttribute("data-next"), 10);
    side.setAttribute("data-next", idx + 1);
    var base = "a_" + item + "_" + code + "_" + idx + "_";
    var row = document.createElement("span");
    row.className = "trow extra";
    row.innerHTML =
      '<input class="coef" name="' + base + 'c" inputmode="numeric" maxlength="3" placeholder="1" autocomplete="off" aria-label="коэффициент">' +
      '<input class="f" name="' + base + 'f" placeholder="формула" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="формула">' +
      '<input type="hidden" name="' + base + 't" value="extra">' +
      '<button type="button" class="rm" title="Убрать вещество">×</button>';
    side.insertBefore(row, side.querySelector(".add"));
    row.querySelector("input.f").focus();
  }

  form.addEventListener("click", function (e) {
    var task = e.target.closest("[data-task]");
    var add = e.target.closest(".add");
    if (add) { newRow(add.parentNode); dirty = true; renderTask(task); return; }
    var rm = e.target.closest(".rm");
    if (rm) { rm.parentNode.remove(); dirty = true; renderTask(task); }
  });

  form.addEventListener("input", function (e) {
    dirty = true;
    if (e.target.classList.contains("coef")) e.target.value = e.target.value.replace(/[^0-9]/g, "");
    var task = e.target.closest("[data-task]");
    if (task) renderTask(task);
  });

  // Enter в поле не отправляет форму, а переходит к следующему полю
  form.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.tagName === "INPUT") {
      e.preventDefault();
      var inputs = Array.from(form.querySelectorAll("input:not([type=hidden])"));
      var next = inputs[inputs.indexOf(e.target) + 1];
      if (next) next.focus();
    }
  });

  form.querySelectorAll("[data-task]").forEach(renderTask);
  form.addEventListener("submit", function () { dirty = false; });
  window.addEventListener("beforeunload", function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });
})();
