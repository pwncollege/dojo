function copyToClipboard(event) {
  const input = document.getElementById('user-token-result');
  input.select();
  input.setSelectionRange(0, 99999);
  document.execCommand("copy");

  $(event.target).tooltip({
    title: "Copied!",
    trigger: "manual"
  });
  $(event.target).tooltip("show");

  setTimeout(function() {
    $(event.target).tooltip("hide");
  }, 1500);
}

document.addEventListener("DOMContentLoaded", function () {
    if (new Date() >= new Date("2025-03-01")) return;

    const urlParams = new URLSearchParams(window.location.search);
    const theme = urlParams.get("theme");

    if (theme) {
        document.body.classList.add(`theme-${theme}`);
        localStorage.setItem('theme', theme);
    } else {
        const storedTheme = localStorage.getItem('theme');
        document.body.classList.add(`theme-${storedTheme}`);
    }
});