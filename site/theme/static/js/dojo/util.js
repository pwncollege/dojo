window.Dojo = {
    config: {urlRoot: init.urlRoot, csrfNonce: init.csrfNonce},

    fetch(url, options = {}) {
        options.credentials = "same-origin";
        options.headers = {...options.headers, "Accept": "application/json", "Content-Type": "application/json", "CSRF-Token": Dojo.config.csrfNonce};
        return window.fetch(Dojo.config.urlRoot + url, options);
    },

    submitFlag(dojo, module, challenge, submission) {
        return Dojo.fetch(`/pwncollege_api/v1/dojos/${dojo}/${module}/${challenge}/solve`, {method: "POST", body: JSON.stringify({submission})})
            .then(response => response.status === 403 ? {status: "authentication_required"} : response.json());
    },
};

$.fn.serializeJSON = function() {
    return Object.fromEntries(new FormData(this[0]));
};

function formatTime(value) {
    const date = new Date(value);
    const day = date.getDate();
    const suffix = [11, 12, 13].includes(day) ? "th" : ["th", "st", "nd", "rd"][day % 10] || "th";
    const pad = number => String(number).padStart(2, "0");
    const time = `${date.getHours() % 12 || 12}:${pad(date.getMinutes())}:${pad(date.getSeconds())} ${date.getHours() < 12 ? "AM" : "PM"}`;
    return `${date.toLocaleString("en-US", {month: "long"})} ${day}${suffix}, ${time}`;
}

$(() => {
    $('[data-toggle="tooltip"]').tooltip();
    $("[data-time]").each((i, element) => { element.innerText = formatTime(element.dataset.time); });
    $("pre code").each((i, block) => hljs.highlightBlock(block));
});

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