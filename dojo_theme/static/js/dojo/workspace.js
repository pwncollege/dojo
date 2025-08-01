function process_content_operation_recursive(operations, content) {
    if (operations.length == 0) {
        return;
    }

    var operation = operations[0];

    if (operation.match(/GET:.*/) != null) {
        fetch(operation.substring(4), {
            method: "GET",
            credentials: 'same-origin',
        }).then(() => {
            process_content_operation_recursive(operations.slice(1, operations.length), content);
        });
    }
    else if (operation.match(/GET&RENDER:.*/)) {
        var op = operation.substring(11);
        var delin = op.indexOf(":");
        url = op.substring(delin + 1);
        param = op.substring(0, delin);

        fetch(url, {
            method: "GET",
            credentials: "same-origin",
        }).then(function (response) {
            return response.json();
        }).then(function (result) {
            content.src = result[param];
            process_content_operation_recursive(operations.slice(1, operations.length), content);
        })
    }
    else if (operation.match(/RENDER:.*/)) {
        content.src = operation.substring(7);
    }
    else {
        console.log("Error processing content operation: " + operation);
    }

    process_content_operation_recursive(operations.slice(1, operations.length), content);
}

function set_content(option) {
    var operations = option.value.split(";");
    var content = document.getElementById("challenge-content");

    process_content_operation_recursive(operations, content);
}

function start_challenge(privileged) {
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

            set_content(document.getElementById("workspace-select"));

            $(".btn-challenge-start")
            .removeClass("disabled")
            .removeClass("btn-disabled")
            .prop("disabled", false);
        })
    });
}

function challenge_start_callback(event) {
    event.preventDefault();

    $(".btn-challenge-start")
    .addClass("disabled")
    .addClass("btn-disabled")
    .prop("disabled", true);

    if (document.getElementById("start").contains(event.target)) {
        $(".option-active").removeClass("option-active");
        document.getElementById("start").classList.add("option-active");
        start_challenge(false);
    }
    else if (document.getElementById("start-priv") != null && document.getElementById("start-priv").contains(event.target)) {
        $(".option-active").removeClass("option-active");
        document.getElementById("start-priv").classList.add("option-active");
        start_challenge(true);
    }
    else if (document.getElementById("restart").contains(event.target)) {
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
            start_challenge(result.practice);
        });
    }
    else {
        console.log("Failed to start challenge.");

        $(".btn-challenge-start")
        .removeClass("disabled")
        .removeClass("btn-disabled")
        .prop("disabled", false);
    }
}

function submit_flag(flag) {
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
            flag_input.classList.add("submit-incorrect");
        }
        else if (response.data.status == "correct") {
            flag_input.placeholder = "Correct!";
            flag_input.classList.add("submit-correct");
        }
        else if (response.data.status == "already_solved") {
            flag_input.placeholder = "Already Solved.";
            flag_input.classList.add("submit-correct");
        }
        else {
            flag_input.placeholder = "Submission Failed.";
            flag_input.classList.add("submit-warn");
        }
    });
}

function hide_navbar() {
    $(".navbar").addClass("navbar-hidden");
    $("main").addClass("main-navbar-hidden");
}

function show_navbar() {
    $(".navbar").removeClass("navbar-hidden");
    $("main").removeClass("main-navbar-hidden");
}

function do_fullscreen() {
    if (document.getElementsByClassName("navbar")[0].classList.contains("navbar-hidden")) {
        show_navbar();
    }
    else {
        hide_navbar();
    }
}

$(() => {
    var option = document.getElementById("active");
    option.selected = true;
    set_content(option);

    if (new URLSearchParams(window.location.search).has("hide-navbar")) {
        $("nav").hide();
    }
    $("footer").hide();

    $("#workspace-select").change((event) => {
        event.preventDefault();
        document.cookie = `previous_workspace=${event.target.options[event.target.selectedIndex].text}; expires=${(new Date(Date.now() + 30 * 24 * 60 * 60 * 1000))}; path=/workspace;`;
        set_content(event.target);
    });

    $(".btn-challenge-start").click(challenge_start_callback);

    $("#flag-input").on("input", function(event) {
        event.preventDefault();
        $(this).removeClass("submit-correct submit-incorrect submit-warn");
        if ($(this).val().match(/pwn.college{.*}/)) {
            submit_flag($(this).val());
        }
    });

    $("#fullscreen").click((event) => {
        event.preventDefault();
        $("#fullscreen i").toggleClass("fa-compress fa-expand");
        // If the window is not an iframe, this will refer to its own do_fullscreen function.
        // Otherwise it will call the do_fullscreen function of the window which we are iframed into.
        window.parent.do_fullscreen();
    });
});