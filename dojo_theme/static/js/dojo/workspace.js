function animateBanner(prefix) {
    CTFd.fetch("/pwncollege_api/v1/docker", {
        method: "GET",
        credentials: 'same-origin'
    }).then(function (response) {
        // We can assume the response will be OK since this is called by the flag submission code.
        return response.json();
    }).then(function (result) {
        $("#notif-banner").html(prefix + ` ${result.challengeName} from ${result.dojoName}!`);
        $("#notif-banner").removeClass("notif-animate");
        // Force reflow of element to play animation again.
        document.getElementById("notif-banner").offsetHeight;
        $("#notif-banner").addClass("notif-animate")
    });
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

function isPrivileged() {
    if ($("#challenge-switch").length == 0) {
        return false;
    }

    return $("#challenge-switch").attr("data-privileged") == "true";
}

function startChallenge(privileged) {
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

function setSwitch(invert) {
    // XOR
    if (isPrivileged() != invert) {
        $("#challenge-switch").find(".fas").addClass("fa-unlock").removeClass("fa-lock");
    }
    else {
        $("#challenge-switch").find(".fas").addClass("fa-lock").removeClass("fa-unlock");
    }
    if (isPrivileged()) {
        $("#challenge-switch").attr("title", "Restart unprivileged");
    }
    else {
        $("#challenge-switch").attr("title", "Restart privileged");
    }
}

function challengeStartCallback(event) {
    event.preventDefault();

    $(".btn-challenge-start")
    .addClass("disabled")
    .addClass("btn-disabled")
    .prop("disabled", true);

    if (document.getElementById("challenge-restart").contains(event.target)) {
        startChallenge(isPrivileged());
    }
    else if (document.getElementById("challenge-switch") != null && document.getElementById("challenge-switch").contains(event.target)) {
        if (isPrivileged()) {
            $("#challenge-switch").attr("data-privileged", "false");
        }
        else {
            $("#challenge-switch").attr("data-privileged", "true");
        }
        setSwitch(false);
        startChallenge(isPrivileged());
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
    flag_input = document.getElementById("flag-input");
    flag_input.value = "";
    flag_input.placeholder = "Submitting...";

    var body = {
        'challenge_id': parseInt(document.getElementById("current-challenge-id").value),
        'submission': flag,
    };
    var params = {};

    CTFd.api.post_challenge_attempt(params, body)
    .then(function (response) {
        if (response.data.status == "incorrect") {
            flag_input.placeholder = "Incorrect!";
            $(".workspace-input").addClass("submit-incorrect");
        }
        else if (response.data.status == "correct") {
            flag_input.placeholder = "Correct!";
            $(".workspace-input").addClass("submit-correct");
            animateBanner("Successfully completed");
        }
        else if (response.data.status == "already_solved") {
            flag_input.placeholder = "Already Solved.";
            $(".workspace-input").addClass("submit-correct");
            animateBanner("Solved");
        }
        else {
            flag_input.placeholder = "Submission Failed.";
            $(".workspace-input").addClass("submit-warn");
        }
    });
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
        $(".workspace-input").removeClass("submit-correct submit-incorrect submit-warn");
        $(this).attr("placeholder", "Flag");
        if ($(this).val().match(/pwn.college{.*}/)) {
            submitFlag($(this).val());
        }
    });
    $("#flag-input").on("keypress", function(event) {
        $(".workspace-input").removeClass("submit-correct submit-incorrect submit-warn");
        $(this).attr("placeholder", "Flag");
        if (event.key === "Enter" || event.keyCode === 13) {
            submitFlag($(this).val());
        }
    });

    if ($("#challenge-switch").length) {
        $("#challenge-switch").on("mouseenter", function(event) {
            setSwitch(true);
        }).on("mouseleave", function(event) {
            setSwitch(false);
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