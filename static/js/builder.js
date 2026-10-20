// Конструктор задания: переключение видимости веществ (авто → показать → скрыть → авто)
// и живое обновление строки «Ученик видит» без сохранения. Логика повторяет logic.item_view и render.preview_html.
(function () {
  var form = document.getElementById("items-form");
  if (!form) return;
  var FLAGS = ["show_reactants", "show_products", "show_count", "hide_water"];
  var PLUS = '<span class="plus"> + </span>';
  var dirty = false;

  function flagsOf(item) {
    var flags = {};
    FLAGS.forEach(function (f) {
      var sel = item.querySelector('select[data-flag="' + f + '"]');
      flags[f] = sel && sel.value !== "" ? sel.value === "1" : form.dataset[f] === "1";
    });
    return flags;
  }

  function renderChip(chip, state) {
    var v = chip.querySelector("input").value;
    chip.classList.remove("auto", "shown", "hidden", "auto-shown", "auto-hidden");
    if (v === "1") chip.classList.add("shown");
    else if (v === "0") chip.classList.add("hidden");
    else chip.classList.add("auto", state.auto ? "auto-shown" : "auto-hidden");
    chip.querySelector(".state").textContent = v === "1" ? "показ" : v === "0" ? "скрыто" : "авто";
    chip.title = v !== "" ? "задано вручную" : state.water ? "скрыта опцией «прятать воду»" : "по настройке стороны";
  }

  function updateItem(item) {
    var flags = flagsOf(item);
    var sides = { L: [], R: [] };
    item.querySelectorAll(".chip").forEach(function (chip) {
      var side = chip.dataset.side;
      var water = chip.dataset.water === "1" && flags.hide_water;
      var auto = water ? false : (side === "L" ? flags.show_reactants : flags.show_products);
      var v = chip.querySelector("input").value;
      var visible = v === "" ? auto : v === "1";
      renderChip(chip, { auto: auto, water: water });
      sides[side].push({ visible: visible, byWater: v === "" && water, html: chip.querySelector(".chip-term").innerHTML });
    });
    var preview = item.querySelector("[data-preview]");
    ["L", "R"].forEach(function (side) {
      var parts = [], hidden = 0;
      sides[side].forEach(function (s) {
        if (s.visible) parts.push('<span class="term">' + s.html + "</span>");
        else if (!s.byWater) {
          hidden++;
          if (flags.show_count) parts.push('<span class="term blank">?</span>');
        }
      });
      if (!flags.show_count && hidden) parts.push('<span class="term blank">…</span>');
      preview.querySelector('[data-pv="' + side + '"]').innerHTML =
        parts.join(PLUS) || '<span class="term blank">…</span>';
    });
    preview.querySelector("[data-pv-water]").hidden = !flags.hide_water;
  }

  function markDirty() {
    dirty = true;
    var note = form.querySelector(".unsaved");
    if (note) note.hidden = false;
  }

  form.querySelectorAll("[data-item]").forEach(function (item) {
    item.querySelectorAll(".chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var input = chip.querySelector("input");
        input.value = input.value === "" ? "1" : input.value === "1" ? "0" : "";
        updateItem(item);
        markDirty();
      });
    });
    item.querySelectorAll(".item-settings select").forEach(function (sel) {
      sel.addEventListener("change", function () {
        sel.classList.toggle("changed", sel.value !== "");
        updateItem(item);
        markDirty();
      });
    });
    updateItem(item);
  });

  // отправка формы (сохранение, «Как видит ученик», перемещение пунктов) сохраняет изменения
  form.addEventListener("submit", function (e) {
    dirty = false;
    var note = form.querySelector(".unsaved");
    if (note && e.submitter && e.submitter.getAttribute("formtarget") === "_blank") note.hidden = true;
  });
  window.addEventListener("beforeunload", function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });
})();
