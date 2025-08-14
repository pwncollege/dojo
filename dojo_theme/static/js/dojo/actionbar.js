function ab_controls(event) {
    return $(event.target).closest(".workspace-controls");
}

function ab_selectService(service) {
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

function ab_animateBanner(event, message, type) {
    const color = {
        success: "var(--brand-green)",
        error:   "var(--error)",
        warn:    "var(--warn)"
    }[type] ?? "var(--warn)";
    const animation = type === "success" ? "animate-banner" : "animate-banner-fast";

    ab_controls(event).find("#workspace-notification-banner").removeClass("animate-banner animate-banner-fast");
    ab_controls(event).find("#workspace-notification-banner")[0].offsetHeight;  // Force reflow of element to play animation again.
    ab_controls(event).find("#workspace-notification-banner")
      .html(message)
      .css("border-color", color)
      .addClass(animation);
}

function ab_submitFlag(event) {
    var body = {
        'challenge_id': parseInt(ab_controls(event).find("#current-challenge-id").val()),
        'submission': $(event.target).val(),
    };
    var params = {};

    CTFd.api.post_challenge_attempt(params, body)
    .then(function (response) {
        const challengeName = ab_controls(event).find("#current-challenge-id").attr("data-challenge-name");
        if (response.data.status == "incorrect") {
            ab_animateBanner(event, "Incorrect!", "error");
        }
        else if (response.data.status == "correct") {
            ab_animateBanner(event, `&#127881 Successfully completed <b>${challengeName}</b>! &#127881`, "success");
        }
        else if (response.data.status == "already_solved") {
            ab_animateBanner(event, `&#127881 Solved <b>${challengeName}</b>! &#127881`, "success");
        }
        else {
            ab_animateBanner(event, "Submission Failed.", "warn");
        }
    });
}

function ab_startChallenge(event) {
    const privileged = ab_controls(event).find("#workspace-change-privilege").attr("data-privileged") === "true";

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

            ab_selectService(ab_controls(event).find("#workspace-select").val());

            ab_controls(event).find(".btn-challenge-start")
            .removeClass("disabled")
            .removeClass("btn-disabled")
            .prop("disabled", false);
        })
    });
}

function ab_challengeStartCallback(event) {
    event.preventDefault();

    ab_controls(event).find(".btn-challenge-start")
    .addClass("disabled")
    .addClass("btn-disabled")
    .prop("disabled", true);

    if (ab_controls(event).find("#challenge-restart")[0].contains(event.target)) {
        ab_startChallenge(event);
    }
    else if (ab_controls(event).find("#workspace-change-privilege").length > 0 && ab_controls(event).find("#workspace-change-privilege")[0].contains(event.target)) {
        ab_controls(event).find("#workspace-change-privilege").attr("data-privileged", (_, v) => v !== "true");
        ab_displayPrivileged(event, false);
        ab_startChallenge(event);
    }
    else {
        console.log("Failed to start challenge.");

        ab_controls(event).find(".btn-challenge-start")
        .removeClass("disabled")
        .removeClass("btn-disabled")
        .prop("disabled", false);
    }
}

function ab_displayPrivileged(event, invert) {
    const button = ab_controls(event).find("#workspace-change-privilege");
    const privileged = button.attr("data-privileged") === "true";
    const lockStatus = privileged === invert;

    button.find(".fas")
        .toggleClass("fa-lock", lockStatus)
        .toggleClass("fa-unlock", !lockStatus);

    button.attr("title", privileged ? "Restart unprivileged"
                                    : "Restart privileged");
}

function ab_loadWorkspace() {
    if ($("#workspace-iframe").length == 0 ) {
        return;
    }
    var previousWorkspace = localStorage.getItem("previousWorkspace");
    var workspaceSelect = $("#workspace-iframe").closest(".challenge-workspace").find("#workspace-select")[0];
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
    ab_selectService(option.value);
}

$(() => {
    ab_loadWorkspace();
    $(".workspace-controls").each(function () {
        $(this).find("#workspace-select").change((event) => {
            event.preventDefault();
            localStorage.setItem("previousWorkspace", event.target.options[event.target.selectedIndex].text);
            ab_selectService(event.target.value);
        });

        $(this).find("#flag-input").on("input", function(event) {
            event.preventDefault();
            if ($(this).val().match(/pwn.college{.*}/)) {
                ab_submitFlag(event);
            }
        });
        $(this).find("#flag-input").on("keypress", function(event) {
            if (event.key === "Enter" || event.keyCode === 13) {
                ab_submitFlag(event);
            }
        });

        $(this).find(".btn-challenge-start").click(ab_challengeStartCallback);

        if ($(this).find("#workspace-change-privilege").length) {
            $(this).find("#workspace-change-privilege").on("mouseenter", function(event) {
                ab_displayPrivileged(event, true);
            }).on("mouseleave", function(event) {
                ab_displayPrivileged(event, false);
            });
        }

        $(this).find("#fullscreen").click((event) => {
            event.preventDefault();
            ab_controls(event).find("#fullscreen i").toggleClass("fa-compress fa-expand");
            // Pages using the actionbar should implement their own fullscreen.
            doFullscreen(event);
        })
    });
});