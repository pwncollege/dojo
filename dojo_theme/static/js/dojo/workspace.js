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

function updateWorkspace(data) {
    $("#current-challenge-id").prop("value", data["challenge-id"])
                              .attr("data-challenge-name", data["challenge-name"]);
    
    var priv = $("#workspace-change-privilege")
    if (priv.length > 0) {
        priv.attr("data-privileged", data["challenge-privilege"])
        displayPrivileged({"target": priv[0]}, false);
    }

    var current = $("#workspace-select").prop("value")
    console.log(current);
}

$(() => {
    const channel = new BroadcastChannel("Challenge-Sync-Channel");

    if (new URLSearchParams(window.location.search).has("hide-navbar")) {
        hideNavbar();
    }
    $(".close-link").hide();
    $("footer").hide();

    channel.addEventListener("message", (event) => {
        console.log(event.data);
        updateWorkspace(event.data);
    });
})