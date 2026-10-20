// Вставка спецсимволов в поле уравнения и живой предпросмотр разбора.
(function () {
  document.querySelectorAll(".symbols").forEach(function (bar) {
    var field = document.getElementById(bar.getAttribute("data-target"));
    if (!field) return;
    bar.addEventListener("mousedown", function (e) { e.preventDefault(); });  // не отнимать фокус у поля
    bar.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-insert]");
      if (!btn) return;
      var tpl = btn.getAttribute("data-insert");
      var caret = tpl.indexOf("|");
      var text = tpl.replace("|", "");
      var start = field.selectionStart, end = field.selectionEnd;
      var selected = field.value.slice(start, end);
      // выделенный текст оборачивается: «t» + «над ^( )» -> «^(t)»
      if (selected && caret >= 0) text = text.slice(0, caret) + selected + text.slice(caret);
      field.setRangeText(text, start, end, "end");
      if (caret >= 0) {
        var pos = start + caret + selected.length;
        field.setSelectionRange(pos, pos);
      }
      field.focus();
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });

  document.querySelectorAll("[data-live-preview]").forEach(function (box) {
    var field = document.getElementById(box.getAttribute("data-source"));
    var body = box.querySelector(".live-body");
    var timer = null, last = field.value;
    field.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var text = field.value.trim();
        if (text === last) return;
        last = text;
        if (!text) { body.innerHTML = ""; return; }
        var url = box.getAttribute("data-live-preview") + "?text=" + encodeURIComponent(text);
        if (box.dataset.exclude) url += "&exclude=" + box.dataset.exclude;
        fetch(url, { credentials: "same-origin" })
          .then(function (r) { return r.ok ? r.text() : ""; })
          .then(function (html) { if (field.value.trim() === text) body.innerHTML = html; });
      }, 300);
    });
  });
})();
