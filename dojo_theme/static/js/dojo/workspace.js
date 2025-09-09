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
    const channel = new BroadcastChannel("Challenge-Sync-Channel");

    if (new URLSearchParams(window.location.search).has("hide-navbar")) {
        hideNavbar();
    }
    $(".close-link").hide();
    $("footer").hide();

    channel.addEventListener("message", (event) => {
        console.log(event);
    });
})