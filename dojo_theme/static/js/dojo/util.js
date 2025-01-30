function copyToClipboard(event) {
    event.preventDefault();
    const text = event.currentTarget.dataset.copy;
    navigator.clipboard.writeText(text)
    .then(() => {
        const tooltip = event.currentTarget.querySelector("#tooltip");
        const original = tooltip.innerText;
        tooltip.innerText = "Copied!";
        setTimeout(() => {
            tooltip.innerText = original;
        }, 1000);
    })
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