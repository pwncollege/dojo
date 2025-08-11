function animateBanner(message, type) {
    const color = {
        success: "var(--brand-green)",
        error:   "var(--error)",
        warn:    "var(--warn)"
    }[type] ?? "var(--warn)";
    const animation = type === "success" ? "animate-banner" : "animate-banner-fast";

    $("#workspace-notification-banner").removeClass("animate-banner animate-banner-fast");
    $("#workspace-notification-banner").offsetHeight;  // Force reflow of element to play animation again.
    $("#workspace-notification-banner")
      .html(message)
      .css("border-color", color)
      .addClass(animation);
}

function selectService(service) {
    const content = document.getElementById("workspace-content");
    const url = new URL("/pwncollege_api/v1/workspace", window.location.origin);
    url.searchParams.set("service", service);
    fetch(url, {
        method: "GET",
        credentials: "same-origin"
    })
    .then(response => response.json())
    .then(result => {
        content.src = result["iframe_src"];
    });
}

function startChallenge() {
    const privileged = $("#workspace-change-privilege").attr("data-privileged") === "true";

    CTFd.fetch("/pwncollege_api/v1/docker", {
        method: "GET",
        credentials: 'same-origin'
    }).then(function (response) {
        if (response.status === 403) {
            // User is not logged in or CTF is paused.
            window.location =
                CTFd.config.urlRoot +
                "/login?next=" +
                CTFd.config.urlRoot +
                window.location.pathname +
                window.location.hash;
        }
        return response.json();
    }).then(function (result) {
        if (result.success == false) {
            return;
        }

        var params = {
            "dojo": result.dojo,
            "module": result.module,
            "challenge": result.challenge,
            "practice": privileged,
        };

        CTFd.fetch('/pwncollege_api/v1/docker', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        }).then(function (response) {
            return response.json;
        }).then(function (result) {
            if (result.success == false) {
                return;
            }

            selectService($("#workspace-select").val());

            $(".btn-challenge-start")
            .removeClass("disabled")
            .removeClass("btn-disabled")
            .prop("disabled", false);
        })
    });
}

function displayPrivileged(invert) {
    const button = $("#workspace-change-privilege");
    const privileged = button.attr("data-privileged") === "true";
    const lockStatus = privileged === invert;

    button.find(".fas")
        .toggleClass("fa-lock", lockStatus)
        .toggleClass("fa-unlock", !lockStatus);

    button.attr("title", privileged ? "Restart unprivileged"
                                    : "Restart privileged");
}

function challengeStartCallback(event) {
    event.preventDefault();

    $(".btn-challenge-start")
    .addClass("disabled")
    .addClass("btn-disabled")
    .prop("disabled", true);

    if (document.getElementById("challenge-restart").contains(event.target)) {
        startChallenge();
    }
    else if (document.getElementById("workspace-change-privilege") != null && document.getElementById("workspace-change-privilege").contains(event.target)) {
        $("#workspace-change-privilege").attr("data-privileged", (_, v) => v !== "true");
        displayPrivileged(false);
        startChallenge();
    }
    else {
        console.log("Failed to start challenge.");

        $(".btn-challenge-start")
        .removeClass("disabled")
        .removeClass("btn-disabled")
        .prop("disabled", false);
    }
}

function submitFlag(flag) {
    var body = {
        'challenge_id': parseInt(document.getElementById("current-challenge-id").value),
        'submission': flag,
    };
    var params = {};

    CTFd.api.post_challenge_attempt(params, body)
    .then(function (response) {
        const challengeName = $("#current-challenge-id").attr("data-challenge-name");
        if (response.data.status == "incorrect") {
            animateBanner("Incorrect!", "error");
        }
        else if (response.data.status == "correct") {
            animateBanner(`&#127881 Successfully completed <b>${challengeName}</b>! &#127881`, "success");
            markChallengeAsSolved();
        }
        else if (response.data.status == "already_solved") {
            animateBanner(`&#127881 Solved <b>${challengeName}</b>! &#127881`, "success");
        }
        else {
            animateBanner("Submission Failed.", "warn");
        }
    });
}

// change the challenge icon to solved
function markChallengeAsSolved(){
    const $parent = window.parent.$; // Use parent jQuery from iframe context 
    const $activeChallenge = $parent('.challenge-active')
    if($activeChallenge.length) {
        $flagIcon = $activeChallenge.find('i.challenge-unsolved');
        $flagIcon.removeClass('challenge-unsolved')
                 .addClass('challenge-solved');
    }
}

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
    if (new URLSearchParams(window.location.search).has("hide-navbar")) {
        hideNavbar();
    }
    $("footer").hide();

    var previousWorkspace = localStorage.getItem("previousWorkspace");
    var workspaceSelect = document.getElementById("workspace-select");
    var option = workspaceSelect.options[0];
    if (previousWorkspace && workspaceSelect) {
        for (var i = 0; i < workspaceSelect.options.length; i++) {
            if (workspaceSelect.options[i].text === previousWorkspace) {
                option = workspaceSelect.options[i];
                option.selected = true;
                break;
            }
        }
    }
    selectService(option.value);

    $("#workspace-select").change((event) => {
        event.preventDefault();
        localStorage.setItem("previousWorkspace", event.target.options[event.target.selectedIndex].text);
        selectService(event.target.value);
    });

    $(".btn-challenge-start").click(challengeStartCallback);

    $("#flag-input").on("input", function(event) {
        event.preventDefault();
        if ($(this).val().match(/pwn.college{.*}/)) {
            submitFlag($(this).val());
        }
    });
    $("#flag-input").on("keypress", function(event) {
        if (event.key === "Enter" || event.keyCode === 13) {
            submitFlag($(this).val());
        }
    });

    if ($("#workspace-change-privilege").length) {
        $("#workspace-change-privilege").on("mouseenter", function(event) {
            displayPrivileged(true);
        }).on("mouseleave", function(event) {
            displayPrivileged(false);
        });
    }

    $("#fullscreen").click((event) => {
        event.preventDefault();
        $("#fullscreen i").toggleClass("fa-compress fa-expand");
        // If the window is not an iframe, this will refer to its own do_fullscreen function.
        // Otherwise it will call the do_fullscreen function of the window which we are iframed into.
        window.parent.doFullscreen();
    });
});