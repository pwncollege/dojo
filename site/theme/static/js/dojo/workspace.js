function hideNavbar() {
    $(".navbar").addClass("navbar-hidden");
    $("main").addClass("main-navbar-hidden");
}

function showNavbar() {
    $(".navbar").removeClass("navbar-hidden");
    $("main").removeClass("main-navbar-hidden");
}

function doFullscreen() {
    if (document.getElementsByClassName("navbar")[0].classList.contains("navbar-hidden")) {
        showNavbar();
    }
    else {
        hideNavbar();
    }
}

$(() => {
    const query = new URLSearchParams(window.location.search);
    if (query.has("hide-navbar") || query.get("fullscreen") === "true") {
        hideNavbar();
        $("#fullscreen i").removeClass("fa-expand").addClass("fa-compress");
    }
    $(".close-link").hide();
    $("footer").hide();

    channel.addEventListener("message", (event) => {
        window.location.reload();
    });
})
