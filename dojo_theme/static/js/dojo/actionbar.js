function controls(event) {
    return $(event.target).closest(".workspace-controls");
}

function selectService(service) {
    // Pages using the actionbar should define their own iframe.
    const content = document.getElementById("workspace-iframe");
    if (!content) {
        console.log("Missing workspace iframe :(")
        return;
    }
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

function animateBanner(event, message, type) {
    const color = {
        success: "var(--brand-green)",
        error:   "var(--error)",
        warn:    "var(--warn)"
    }[type] ?? "var(--warn)";
    const animation = type === "success" ? "animate-banner" : "animate-banner-fast";

    controls(event).find("#workspace-notification-banner").removeClass("animate-banner animate-banner-fast");
    controls(event).find("#workspace-notification-banner").offsetHeight;  // Force reflow of element to play animation again.
    controls(event).find("#workspace-notification-banner")
      .html(message)
      .css("border-color", color)
      .addClass(animation);
}

function submitFlag(event) {
    var body = {
        'challenge_id': parseInt(controls(event).find("#current-challenge-id").val()),
        'submission': $(event.target).val(),
    };
    var params = {};

    CTFd.api.post_challenge_attempt(params, body)
    .then(function (response) {
        const challengeName = controls(event).find("#current-challenge-id").attr("data-challenge-name");
        if (response.data.status == "incorrect") {
            animateBanner(event, "Incorrect!", "error");
        }
        else if (response.data.status == "correct") {
            animateBanner(event, `&#127881 Successfully completed <b>${challengeName}</b>! &#127881`, "success");
        }
        else if (response.data.status == "already_solved") {
            animateBanner(event, `&#127881 Solved <b>${challengeName}</b>! &#127881`, "success");
        }
        else {
            animateBanner(event, "Submission Failed.", "warn");
        }
    });
}

function startChallenge(event) {
    const privileged = controls(event).find("#workspace-change-privilege").attr("data-privileged") === "true";

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

            selectService(controls(event).find("#workspace-select").val());

            controls(event).find(".btn-challenge-start")
            .removeClass("disabled")
            .removeClass("btn-disabled")
            .prop("disabled", false);
        })
    });
}

function actionbarSetPrivileged(event, privileged) {
    controls(event).find("#workspace-change-privilege").attr("data-privileged", privileged);
    displayPrivileged(false);
}

function challengeStartCallback(event) {
    event.preventDefault();

    controls(event).find(".btn-challenge-start")
    .addClass("disabled")
    .addClass("btn-disabled")
    .prop("disabled", true);

    if (controls(event).find("#challenge-restart")[0].contains(event.target)) {
        startChallenge(event);
    }
    else if (controls(event).find("#workspace-change-privilege").length > 0 && controls(event).find("#workspace-change-privilege")[0].contains(event.target)) {
        controls(event).find("#workspace-change-privilege").attr("data-privileged", (_, v) => v !== "true");
        displayPrivileged(event, false);
        startChallenge(event);
    }
    else {
        console.log("Failed to start challenge.");

        controls(event).find(".btn-challenge-start")
        .removeClass("disabled")
        .removeClass("btn-disabled")
        .prop("disabled", false);
    }
}

function displayPrivileged(event, invert) {
    const button = controls(event).find("#workspace-change-privilege");
    const privileged = button.attr("data-privileged") === "true";
    const lockStatus = privileged === invert;

    button.find(".fas")
        .toggleClass("fa-lock", lockStatus)
        .toggleClass("fa-unlock", !lockStatus);

    button.attr("title", privileged ? "Restart unprivileged"
                                    : "Restart privileged");
}

function loadWorkspace() {
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
}

$(() => {
    $(".workspace-controls").each(function () {
        loadWorkspace();
        $(this).find("#workspace-select").change((event) => {
            event.preventDefault();
            localStorage.setItem("previousWorkspace", event.target.options[event.target.selectedIndex].text);
            selectService(event.target.value);
        });

        $(this).find("#flag-input").on("input", function(event) {
            event.preventDefault();
            if ($(this).val().match(/pwn.college{.*}/)) {
                submitFlag(event);
            }
        });
        $(this).find("#flag-input").on("keypress", function(event) {
            if (event.key === "Enter" || event.keyCode === 13) {
                submitFlag(event);
            }
        });

        $(this).find(".btn-challenge-start").click(challengeStartCallback);

        if ($(this).find("#workspace-change-privilege").length) {
            $(this).find("#workspace-change-privilege").on("mouseenter", function(event) {
                displayPrivileged(event, true);
            }).on("mouseleave", function(event) {
                displayPrivileged(event, false);
            });
        }

        $(this).find("#fullscreen").click((event) => {
            event.preventDefault();
            controls(event).find("#fullscreen i").toggleClass("fa-compress fa-expand");
            // Pages using the actionbar should implement their own fullscreen.
            doFullscreen(event);
        })
    });
});