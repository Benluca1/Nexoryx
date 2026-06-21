// Copy-Buttons + OS-Auto-Erkennung für die Nexoryx-Install-Seite.

(function () {
  "use strict";

  // --- Copy-Buttons ---
  function wireCopy() {
    document.querySelectorAll(".copybtn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var sel = btn.getAttribute("data-copy-target");
        var el = sel ? document.querySelector(sel) : null;
        var text = el ? el.textContent : btn.getAttribute("data-copy") || "";
        navigator.clipboard.writeText(text.trim()).then(function () {
          var old = btn.textContent;
          btn.textContent = "kopiert ✓";
          btn.classList.add("ok");
          setTimeout(function () {
            btn.textContent = old;
            btn.classList.remove("ok");
          }, 1600);
        });
      });
    });
  }

  // --- OS-Erkennung ---
  function detectOS() {
    var ua = (navigator.userAgent || "").toLowerCase();
    var plat = (navigator.platform || "").toLowerCase();
    if (ua.indexOf("windows") !== -1 || plat.indexOf("win") !== -1) return "Windows";
    if (ua.indexOf("mac") !== -1 || plat.indexOf("mac") !== -1) {
      // iPadOS meldet sich teils als Mac
      return ua.indexOf("mobile") !== -1 ? "iOS/iPadOS" : "macOS";
    }
    if (ua.indexOf("android") !== -1) return "Android";
    if (ua.indexOf("linux") !== -1 || plat.indexOf("linux") !== -1) return "Linux";
    return "Linux";
  }

  function showOSHint() {
    var os = detectOS();
    var hint = document.getElementById("os-hint");
    if (hint) {
      var span = hint.querySelector("[data-os]");
      if (span) span.textContent = os;
    }
    // Passenden OS-Tab markieren (falls vorhanden)
    document.querySelectorAll("[data-os-tab]").forEach(function (tab) {
      if (tab.getAttribute("data-os-tab").toLowerCase() === os.toLowerCase().split("/")[0]) {
        tab.classList.add("active");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireCopy();
    showOSHint();
  });
})();
