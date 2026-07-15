// To use the actionbar, the following parameters should be met:
// 1. There is an iframe for controlled workspace content with the id "workspace-iframe"
// 2. The actionbar and iframe are descendants of a common ancestor with the class "challenge-workspace"
// 3. In fullpage mode (data-popout="false"), the page implements a function, doFullscreen(event), to handle a fullscreen event
// 4. Optionally, the page can have a div with the class "workspace-ssh" which is displayed when the SSH service is
//    selected (fullpage mode) or toggled in place of the iframe via the portless service button (pop-out mode).

// Returns the controls object containing the origin of the event.
function context(event) {
    return $(event.target).closest(".workspace-controls");
}

function isPopout(root) {
    return root.attr("data-popout") === "true";
}

function serviceName(service) {
    return service.split(": ")[0];
}

function servicePort(service) {
    return service.split(": ")[1];
}

function isSpecialService(service) {
    const specialServices = ["terminal", "code", "desktop"];
    const specialPorts = ["7681", "8080", "6080"];
    const index = specialServices.indexOf(serviceName(service));
    return index > -1 && index == specialPorts.indexOf(servicePort(service));
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

// Get most recent service which is offered by the given root actionbar.
function getRecentService(root) {
    var options = [];
    root.find(".workspace-service").each((index, element) => {
        options.push($(element).attr("data-service"));
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

function showWorkspaceLoadError(content, result) {
    content.src = "";
    animateBanner(
        {target: $(content).closest(".challenge-workspace").find(".workspace-controls")[0]},
        result.error,
        "error"
    );
}

function specialSelect(name, content) {
    const url = new URL("/pwncollege_api/v1/workspace", window.location.origin);
    url.searchParams.set("service", name);
    fetch(url, {
        method: "GET",
        credentials: "same-origin"
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            const url = new URL(result["iframe_src"]);
            // Set the port if in dev environment (may be forwarded via a server)
            if (result["setPort"]) {
                url.port = window.location.port;
            }

            content.src = url.toString();
        }
        else {
            showWorkspaceLoadError(content, result);
        }
    });
}

function portSelect(port, content) {
    const url = new URL("/pwncollege_api/v1/workspace", window.location.origin);
    url.searchParams.set("port", port);
    fetch(url, {
        method: "GET",
        credentials: "same-origin"
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            const url = new URL(result["iframe_src"]);
            // Set the port if in dev environment (may be forwarded via a server)
            if (result["setPort"]) {
                url.port = window.location.port;
            }

            content.src = url.toString();
        }
        else {
            showWorkspaceLoadError(content, result);
        }
    });
}

function loadIframe(service, content) {
    if (isSpecialService(service)) {
        specialSelect(serviceName(service), content);
    }
    else {
        portSelect(servicePort(service), content);
    }
}

function popoutUrl(service) {
    if (isSpecialService(service)) {
        return "/workspace/" + encodeURIComponent(serviceName(service));
    }
    return "/workspace/" + encodeURIComponent(servicePort(service));
}

function selectService(service, log=true) {
    const content = document.getElementById("workspace-iframe");
    if (!content) {
        console.log("Missing workspace iframe :(")
        return;
    }
    if (log) {logService(service);}
    const root = $(content).closest(".challenge-workspace").find(".workspace-controls");
    root.find(".workspace-service").each(function () {
        const active = $(this).attr("data-service") === service;
        $(this).toggleClass("active", active);
        $(this).attr("aria-pressed", active ? "true" : "false");
    });
    if (serviceName(service) == "ssh" && servicePort(service) == "") {
        content.src = "";
        $(content).addClass("SSH");
        $(".workspace-ssh").show();
        return;
    }
    else {
        $(content).removeClass("SSH");
        $(".workspace-ssh").hide();
    }
    loadIframe(service, content);
}

function portlessButton(root) {
    return root.find(".workspace-service").filter(function () {
        return servicePort($(this).attr("data-service")) === "";
    });
}

function portedService(root) {
    var service = null;
    root.find(".workspace-service").each(function () {
        const candidate = $(this).attr("data-service");
        if (service === null && servicePort(candidate) !== "") {
            service = candidate;
        }
    });
    return service;
}

function toggleSshInstructions(root, show=null) {
    const workspace = root.closest(".challenge-workspace");
    const button = portlessButton(root);
    const active = show === null ? !button.hasClass("active") : show;
    button.toggleClass("active", active);
    button.attr("aria-pressed", active ? "true" : "false");
    workspace.find(".workspace-ssh").toggle(active);
    workspace.find("#workspace-iframe").toggleClass("SSH", active);
}

function serviceClickCallback(event) {
    event.preventDefault();
    const button = $(event.currentTarget);
    const service = button.attr("data-service");
    if (!isPopout(context(event))) {
        if (button.hasClass("active")) {
            return;
        }
        selectService(service);
        return;
    }
    if (servicePort(service) === "") {
        if (portedService(context(event))) {
            toggleSshInstructions(context(event));
        }
        return;
    }
    const popout = window.open("", "workspace-" + popoutUrl(service).split("/").pop());
    if (!popout) {
        animateBanner(event, "Pop-up blocked — please allow pop-ups for this site.", "warn");
        return;
    }
    let needsNavigation = true;
    try {
        needsNavigation = popout.location.pathname !== popoutUrl(service);
    } catch (error) {}
    if (needsNavigation) {
        popout.location = popoutUrl(service);
    }
    popout.focus();
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

    context(event).find("#flag-input").prop("disabled", true).addClass("disabled");
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
        context(event).find("#flag-input").prop("disabled", false).removeClass("disabled");
        context(event).find(".input-icon").toggleClass("fa-flag fa-spinner fa-spin");
    });
}

function sendChallengeInfo(root, channel) {
    challenge = root.find("#current-challenge-id");
    privilege = root.find("#workspace-change-privilege");

    challengeData = {
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

function setActionbarBusy(root, busy) {
    root.find(".btn-challenge-start")
        .toggleClass("disabled", busy)
        .toggleClass("btn-disabled", busy)
        .prop("disabled", busy);
    root.find("#workspace-change-privilege input").prop("disabled", busy);
}

function actionStartChallenge(event, privileged) {
    const root = context(event);
    const privilegeControl = root.find("#workspace-change-privilege");
    if (privileged === undefined) {
        privileged = privilegeControl.attr("data-privileged") === "true";
    }

    function startFailed(message) {
        setActionbarBusy(root, false);
        privilegeControl.find("input").prop("checked", privilegeControl.attr("data-privileged") === "true");
        animateBanner(event, message || "Failed to start challenge.", "error");
    }

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
            startFailed(result.error);
            return;
        }

        var params = {
            "dojo": result.dojo,
            "module": result.module,
            "challenge": result.challenge,
            "practice": privileged,
        };

        return CTFd.fetch('/pwncollege_api/v1/docker', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        }).then(function (response) {
            return response.json();
        }).then(function (result) {
            if (result.success == false) {
                startFailed(result.error);
                return;
            }

            privilegeControl.attr("data-privileged", privileged ? "true" : "false");
            privilegeControl.find("input").prop("checked", privileged);

            refreshWorkspace(root);
            postStartChallenge(event, channel);

            setActionbarBusy(root, false);
        });
    }).catch(function () {
        startFailed();
    });
}

function actionStartCallback(event) {
    event.preventDefault();
    setActionbarBusy(context(event), true);
    actionStartChallenge(event);
}

function privilegeChangeCallback(event) {
    const checkbox = event.currentTarget;
    const mode = checkbox.checked ? "with sudo access" : "without sudo access";
    if (!window.confirm(`Restart the challenge ${mode}? The running container will be replaced.`)) {
        checkbox.checked = !checkbox.checked;
        return;
    }
    setActionbarBusy(context(event), true);
    actionStartChallenge(event, checkbox.checked);
}

function loadWorkspace(log=true) {
    const content = $("#workspace-iframe");
    if (content.length == 0) {
        return;
    }
    var root = content.closest(".challenge-workspace").find(".workspace-controls");
    if (isPopout(root)) {
        const service = portedService(root);
        if (service) {
            toggleSshInstructions(root, portlessButton(root).hasClass("active"));
            loadIframe(service, content[0]);
        }
        else {
            content.attr("src", "");
            toggleSshInstructions(root, true);
        }
        return;
    }
    var recent = getRecentService(root);
    if (recent == null) {
        recent = root.find(".workspace-service").first().attr("data-service");
    }
    if (recent) {
        selectService(recent, log);
    }
}

function refreshWorkspace(root) {
    if (isPopout(root)) {
        loadWorkspace(false);
        return;
    }
    var active = root.find(".workspace-service.active").attr("data-service");
    if (active) {
        selectService(active, false);
    }
    else {
        loadWorkspace(false);
    }
}

const channel = new BroadcastChannel("Challenge-Sync-Channel");
$(() => {
    loadWorkspace();
    $(".workspace-controls").each(function () {
        $(this).find(".workspace-service").click(serviceClickCallback);

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

        $(this).find("#workspace-change-privilege input").on("change", privilegeChangeCallback);

        $(this).find("#fullscreen").click((event) => {
            event.preventDefault();
            context(event).find("#fullscreen i").toggleClass("fa-compress fa-expand");
            doFullscreen(event);
        })
    });
});
