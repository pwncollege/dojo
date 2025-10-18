// To use the actionbar, the following parameters should be met:
// 1. There is an iframe for controlled workspace content with the id "workspace-iframe"
// 2. The actionbar and iframe are descendants of a common ancestor with the class "challenge-workspace"
// 3. The page implements a function, doFullscreen(event) to handle a fullscreen event
// 4. Optionally, the page can have a div with the class "workspace-ssh" which will be displayed when the SSH option is selected.

// Returns the controls object containing the origin of the event.
function context(event) {
    return $(event.target).closest(".workspace-controls");
}

function getServiceHistory() {
    var raw = localStorage.getItem("service_history");
    if (raw === null) {
        return [];
    }

    return raw.split(", ");
}

function logService(service) {
    var services = getServiceHistory();
    var index = services.indexOf(service);
    if (index >= 0) {
        services.splice(index, 1);
    }
    services.forEach((element, index, array) => {
        service += ", ";
        service += element;
    })
    localStorage.setItem("service_history", service);
}

// Get most recent service which is allowed by the selector within the given root actionbar.
function getRecentService(root) {
    var options = [];
    var allowed = root.find("#workspace-select").find("option");
    allowed.each((index, value) => {
        options.push($(value).prop("value"));
    });
    var history = getServiceHistory();
    var match = null;
    history.forEach((element, index, array) => {
        if (match == null && options.indexOf(element) != -1) {
            match = element;
        }
    });

    return match;
}

function sourceFailed(content, message) {
  content.src = "";
  animateBanner(
      $(content).closest(".challenge-workspace").find("#workspace-select")[0],
      message,
      "error"
  );
}

function specialSelect(serviceName, content) {
    const url = new URL("/pwncollege_api/v1/workspace", window.location.origin);
    url.searchParams.set("service", serviceName);
    fetch(url, {
        method: "GET",
        credentials: "same-origin"
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            content.src = result["iframe_src"];
        }
        else {
            sourceFailed(content, result.error);
        }
    });
}

function selectService(service, log=true) {
    const content = document.getElementById("workspace-iframe");
    if (!content) {
        console.log("Missing workspace iframe :(")
        return;
    }
    if (log) {logService(service);}
    port = service.split(": ")[1];
    service = service.split(": ")[0];
    if (service == "ssh" && port == "") {
        content.src = "";
        $(content).addClass("SSH");
        $(".workspace-ssh").show();
        return;
    }
    else {
        $(content).removeClass("SSH");
        $(".workspace-ssh").hide();
    }
    const specialServices = ["terminal", "code", "desktop"];
    const specialPorts = ["7681", "8080", "6080"];
    if (specialServices.indexOf(service) > -1 && specialServices.indexOf(service) == specialPorts.indexOf(port)) {
        specialSelect(service, content);
    }
    else {
      url = "/workspace/" + port + "/";
      fetch(url, {
          method: "GET",
          credentials: "same-origin"
      }).then((response) => {
          if (!response.ok) {
              return sourceFailed(content, "Failed to connect to service, try restarting or contact dojo admin");
          }
          content.src = url;
      });
    }
}

function animateBanner(event, message, type) {
    const color = {
        success: "var(--brand-green)",
        error:   "var(--error)",
        warn:    "var(--warn)"
    }[type] ?? "var(--warn)";
    const animation = type === "success" ? "animate-banner" : "animate-banner-fast";

    context(event).find("#workspace-notification-banner").removeClass("animate-banner animate-banner-fast");
    context(event).find("#workspace-notification-banner")[0].offsetHeight;  // Force reflow of element to play animation again.
    context(event).find("#workspace-notification-banner")
      .html(message)
      .css("border-color", color)
      .addClass(animation);
}

function actionSubmitFlag(event) {
    const submission = $(event.target).val();

    if (submission == "pwn.college{practice}") {
        animateBanner(event, "This is the practice flag! Find the real flag by restarting the challenge in unprivileged mode.", "warn");
        return;
    }

    context(event).find("input").prop("disabled", true).addClass("disabled");
    context(event).find(".input-icon").toggleClass("fa-flag fa-spinner fa-spin");
    const challenge_id = parseInt(context(event).find("#current-challenge-id").val());

    CTFd.api.post_challenge_attempt({}, {"challenge_id": challenge_id, "submission": submission})
    .then(function (response) {
        const challengeName = context(event).find("#current-challenge-id").attr("data-challenge-name");

        if (response.data.status == "incorrect") {
            animateBanner(event, "Incorrect!", "error");
        }
        else if (response.data.status == "correct") {
            animateBanner(event, `&#127881 Successfully completed <b>${challengeName}</b>! &#127881`, "success");
            if ($(".challenge-active").length) {
                const unsolved_flag = $(".challenge-active").find("i.challenge-unsolved")
                if (unsolved_flag.hasClass("far") && unsolved_flag.hasClass("fa-flag")) {
                    unsolved_flag.removeClass("far").addClass("fas");
                }
                unsolved_flag.removeClass("challenge-unsolved").addClass("challenge-solved");
            }
        }
        else if (response.data.status == "already_solved") {
            animateBanner(event, `&#127881 You've already solved <b>${challengeName}</b>! &#127881`, "success");
        }
        else {
            animateBanner(event, "Submission failed.", "warn");
        }
        context(event).find("input").prop("disabled", false).removeClass("disabled");
        context(event).find(".input-icon").toggleClass("fa-flag fa-spinner fa-spin");
    });
}

function sendChallengeInfo(root, channel) {
    options = []
    root.find("#workspace-select option").each((index, element) => {
        options.push({
            "value": $(element).prop("value"),
            "text": $(element).text(),
        });
    })

    challenge = root.find("#current-challenge-id");
    privilege = root.find("#workspace-change-privilege");

    challengeData = {
        "options": options,
        "challenge-id": challenge.prop("value"),
        "challenge-name": challenge.attr("data-challenge-name"),
        "challenge-privilege": privilege.length > 0 ? privilege.attr("data-privileged") : "false",
    };

    channel.postMessage(challengeData);
}

function postStartChallenge(event, channel) {
    root = context(event);
    sendChallengeInfo(root, channel);
}

function actionStartChallenge(event) {
    const privileged = context(event).find("#workspace-change-privilege").attr("data-privileged") === "true";

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

            selectService(context(event).find("#workspace-select").prop("value"));
            postStartChallenge(event, channel);

            context(event).find(".btn-challenge-start")
            .removeClass("disabled")
            .removeClass("btn-disabled")
            .prop("disabled", false);
        })
    });
}

function actionStartCallback(event) {
    event.preventDefault();

    context(event).find(".btn-challenge-start")
    .addClass("disabled")
    .addClass("btn-disabled")
    .prop("disabled", true);

    if (context(event).find("#challenge-restart")[0].contains(event.target)) {
        actionStartChallenge(event);
    }
    else if (context(event).find("#workspace-change-privilege").length > 0 && context(event).find("#workspace-change-privilege")[0].contains(event.target)) {
        context(event).find("#workspace-change-privilege").attr("data-privileged", (_, v) => v !== "true");
        displayPrivileged(event, false);
        actionStartChallenge(event);
    }
    else {
        console.log("Failed to start challenge.");

        context(event).find(".btn-challenge-start")
        .removeClass("disabled")
        .removeClass("btn-disabled")
        .prop("disabled", false);
    }
}

function displayPrivileged(event, invert) {
    const button = context(event).find("#workspace-change-privilege");
    const privileged = button.attr("data-privileged") === "true";
    const lockStatus = privileged === invert;

    button.find(".fas")
        .toggleClass("fa-lock", lockStatus)
        .toggleClass("fa-unlock", !lockStatus);

    button.attr("title", privileged ? "Restart unprivileged"
                                    : "Restart privileged");
}

function loadWorkspace(log=true) {
    if ($("#workspace-iframe").length == 0 ) {
        return;
    }
    var workspaceRoot = $("#workspace-iframe").closest(".challenge-workspace");
    var recent = getRecentService(workspaceRoot);
    if (recent == null) {
        recent = workspaceRoot.find("#workspace-select").prop("value");
    }
    else {
        workspaceRoot.find("#workspace-select").prop("value", recent);
    }
    selectService(recent, log=log);
}

const channel = new BroadcastChannel("Challenge-Sync-Channel");
$(() => {
    loadWorkspace();
    $(".workspace-controls").each(function () {
        if ($(this).find("option").length < 2) {
            $(this).find("#workspace-select")
                .prop("disabled", true)
                .prop("title", "");
        }

        $(this).find("#workspace-select").change((event) => {
            event.preventDefault();
            selectService(event.target.value);
        });

        $(this).find("#flag-input").on("input", function(event) {
            event.preventDefault();
            if ($(this).val().match(/pwn.college{.*}/)) {
                actionSubmitFlag(event);
            }
        });
        $(this).find("#flag-input").on("keyup", function(event) {
            if (event.key === "Enter") {
                actionSubmitFlag(event);
            }
        });

        $(this).find(".btn-challenge-start").click(actionStartCallback);

        if ($(this).find("#workspace-change-privilege").length) {
            $(this).find("#workspace-change-privilege").on("mouseenter", function(event) {
                displayPrivileged(event, true);
            }).on("mouseleave", function(event) {
                displayPrivileged(event, false);
            });
        }

        $(this).find("#fullscreen").click((event) => {
            event.preventDefault();
            context(event).find("#fullscreen i").toggleClass("fa-compress fa-expand");
            doFullscreen(event);
        })
    });
});
