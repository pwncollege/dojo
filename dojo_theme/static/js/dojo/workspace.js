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
    var changed = false;
    if ($("#current-challenge-id").prop("value") != data["challenge-id"]) {
        changed = true;
    }

    $("#current-challenge-id").prop("value", data["challenge-id"])
                              .attr("data-challenge-name", data["challenge-name"]);
    
    var priv = $("#workspace-change-privilege")
    if (priv.length > 0) {
        priv.attr("data-privileged", data["challenge-privilege"])
        displayPrivileged({"target": priv[0]}, false);
    }

    var selector = $("#workspace-select");
    var current = selector.prop("value");
    var loadedService = false;
    console.log(current);
    selector.empty();
    data.options.forEach((item, index) => {
        selector.append($("<option></option>").attr("value", item.value).text(item.text))
        if (item.value == current) {
            console.log("found match");
            selectService(item.value, true);
            loadedService = true;
        }
    })
    if (!loadedService) {
        console.log("no match");
        loadWorkspace(log=false);
    }
    if (data.options.length > 1) {
        selector.prop("disabled", false);
    }
    else {
        selector.prop("disabled", true);
    }
}

$(() => {
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