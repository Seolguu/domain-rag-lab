// 이론학습(days/*.html) 상단 헤더의 드롭다운 메뉴 — 메인 SPA 헤더와 동일한 동작.
(function () {
  function closeAll() {
    document.querySelectorAll(".day-brand-nav-dropdown.open").forEach(function (d) { d.classList.remove("open"); });
    document.querySelectorAll(".day-brand-nav-trigger.open").forEach(function (t) { t.classList.remove("open"); });
  }
  document.querySelectorAll(".day-brand-nav-group").forEach(function (group) {
    var trigger = group.querySelector(".day-brand-nav-trigger");
    var dropdown = group.querySelector(".day-brand-nav-dropdown");
    if (!trigger || !dropdown) return;
    trigger.addEventListener("click", function (event) {
      event.stopPropagation();
      var willOpen = !dropdown.classList.contains("open");
      closeAll();
      if (willOpen) {
        var rect = trigger.getBoundingClientRect();
        dropdown.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 220)) + "px";
        dropdown.style.top = (rect.bottom + 6) + "px";
        dropdown.classList.add("open");
        trigger.classList.add("open");
      }
    });
    dropdown.querySelectorAll("a").forEach(function (a) { a.addEventListener("click", closeAll); });
  });
  document.addEventListener("click", closeAll);
  window.addEventListener("resize", closeAll);
})();
