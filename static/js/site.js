// Общие мелочи: подтверждения, «отметить все», выгрузка таблицы в CSV.
(function () {
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-confirm]");
    if (el && !window.confirm(el.getAttribute("data-confirm"))) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);

  document.querySelectorAll("[data-check-all]").forEach(function (box) {
    box.addEventListener("change", function () {
      var name = box.getAttribute("data-check-all");
      document.querySelectorAll('input[type=checkbox][name="' + name + '"]:not(:disabled), input[type=checkbox][data-group="' + name + '"]:not(:disabled)')
        .forEach(function (c) { c.checked = box.checked; });
    });
  });

  document.querySelectorAll("[data-download-csv]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var table = document.getElementById(btn.getAttribute("data-download-csv"));
      var lines = Array.from(table.rows).map(function (row) {
        return Array.from(row.cells).map(function (c) {
          return '"' + c.innerText.replace(/"/g, '""') + '"';
        }).join(";");
      });
      var blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = btn.getAttribute("data-filename") || "data.csv";
      a.click();
    });
  });
})();

// Отображение формулы с индексами (упрощённая копия chem/formula.py для предпросмотра).
window.formulaHtml = function (raw) {
  var s = (raw || "").replace(/\s+/g, "").replace(/[*•∙⋅]/g, "·");
  var charge = "";
  var m = s.match(/\^\{?([0-9]*[+-])\}?$/) || s.match(/\{([0-9]*[+-])\}$/);
  if (m) { charge = m[1]; s = s.slice(0, m.index); }
  else if ((m = s.match(/[+-]$/))) { charge = m[0]; s = s.slice(0, -1); }
  var out = "", sub = false, digits = "";
  function esc(c) { return c.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function flush() { if (digits) { out += sub ? "<sub>" + digits + "</sub>" : digits; digits = ""; } }
  for (var i = 0; i < s.length; i++) {
    var ch = s[i];
    if (/[0-9]/.test(ch)) { digits += ch; continue; }
    flush();
    sub = /[A-Za-z)\]]/.test(ch);
    out += esc(ch);
  }
  flush();
  if (charge) out += "<sup>" + esc(charge.replace("-", "−")) + "</sup>";
  return out;
};
