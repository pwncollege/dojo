function submitChallenge(event) {
    event.preventDefault();
    const item = $(event.currentTarget).closest(".accordion-item");
    const challenge_id = parseInt(item.find('#challenge-id').val())
    const answer_input = item.find("#challenge-input");
    const submission = answer_input.val()

    const flag_regex = /pwn.college{.*}/;
    if (submission.match(flag_regex) == null) {
        return;
    }

    answer_input.prop("disabled", true);

    if (submission == "pwn.college{practice}") {
        var message = "This is the practice flag! Find the real flag by pressing the Start button above to launch the challenge in unprivileged mode."
        return renderSubmissionResponse({"data": {"status": "practice", "message": message}}, item);
    }

    return CTFd.api.post_challenge_attempt({}, {"challenge_id": challenge_id, "submission": submission})
        .then(response => renderSubmissionResponse(response, item));
};

function renderSubmissionResponse(response, item) {
    const result = response.data;

    const result_message = item.find("#result-message");
    const result_notification = item.find("#result-notification");
    const answer_input = item.find("#challenge-input");
    const unsolved_flag = item.find(".challenge-unsolved");
    const total_solves = item.find(".total-solves");

    const header = item.find('[id^="challenges-header-"]');
    const current_challenge_id = parseInt(header.attr('id').match(/(\d+)$/)[1]);
    const next_challenge_button = $(`#challenges-header-button-${current_challenge_id + 1}`);

    result_notification.removeClass();
    result_message.text(result.message);

    if (result.status === "authentication_required") {
        window.location =
            CTFd.config.urlRoot +
            "/login?next=" +
            CTFd.config.urlRoot +
            window.location.pathname +
            window.location.hash;
        return;
    } else if (result.status === "incorrect") {
        // Incorrect key
        result_notification.addClass(
            "alert alert-danger alert-dismissable text-center"
        );
        result_notification.slideDown();

        answer_input.removeClass("correct");
        answer_input.addClass("wrong");
        setTimeout(function() {
            answer_input.removeClass("wrong");
        }, 10000);
    } else if (result.status === "practice") {
        // Incorrect key
        result_notification.addClass(
            "alert alert-danger alert-dismissable text-center"
        );
        result_notification.slideDown();

        answer_input.removeClass("correct");
        answer_input.addClass("wrong");
        setTimeout(function() {
            answer_input.removeClass("wrong");
        }, 10000);
    } else if (result.status === "correct") {
        // Challenge Solved
        result_notification.addClass(
            "alert alert-success alert-dismissable text-center"
        );
        result_notification.slideDown();

        unsolved_flag.removeClass("challenge-unsolved");
        unsolved_flag.addClass("challenge-solved");
        if(unsolved_flag.hasClass("far") && unsolved_flag.hasClass("fa-flag")) {
            unsolved_flag.removeClass("far")
            unsolved_flag.addClass("fas")
        }

        total_solves.text(
            (parseInt(total_solves.text().trim().split(" ")[0]) + 1) + " solves"
        );

        answer_input.val("");
        answer_input.removeClass("wrong");
        answer_input.addClass("correct");
        const challenge_name = item.find('#challenge').val()
        const module_name = item.find('#module').val()
        const dojo_name = init.dojo

        const survey_notification = item.find("#survey-notification")

        CTFd.fetch(`/pwncollege_api/v1/dojos/${dojo_name}/${module_name}/${challenge_name}/surveys`, {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
        }).then(function (response) {
            if(response.status != 200) return Promise.reject()
            return response.json()
        }).then(function (data) {
            if(data.type === "none") return
            if(Math.random() > data.probability) return
            survey_notification.addClass(
                "alert-warning alert-dismissable"
            );
            survey_notification.slideDown();
        })
        unlockChallenge(next_challenge_button);
        checkUserAwards()
        .then(handleAwardPopup)
        .catch(error => console.error("Award check failed:", error));
    } else if (result.status === "already_solved") {
        // Challenge already solved
        result_notification.addClass(
            "alert alert-info alert-dismissable text-center"
        );
        result_notification.slideDown();

        answer_input.addClass("correct");
    } else if (result.status === "paused") {
        // CTF is paused
        result_notification.addClass(
            "alert alert-warning alert-dismissable text-center"
        );
        result_notification.slideDown();
    } else if (result.status === "ratelimited") {
        // Keys per minute too high
        result_notification.addClass(
            "alert alert-warning alert-dismissable text-center"
        );
        result_notification.slideDown();

        answer_input.addClass("too-fast");
        setTimeout(function() {
            answer_input.removeClass("too-fast");
        }, 10000);
    }
    setTimeout(function() {
        item.find(".alert").slideUp();
        answer_input.prop("disabled", false);
    }, 10000);
}

function unlockChallenge(challenge_button) {
    if (challenge_button.length && challenge_button.hasClass('disabled')) {
        challenge_button.removeClass('disabled');
        const icon = challenge_button.find('.fa-lock');
        icon.removeClass('fa-lock');
        icon.addClass('fa-flag');

        const item = challenge_button.closest(".accordion-item");
        const module_id = item.find("#module").val();
        const challenge_id = item.find("#challenge").val();
        const description = item.find(".challenge-description");

        CTFd.fetch(`/pwncollege_api/v1/dojos/${init.dojo}/${module_id}/${challenge_id}/description`)
            .then(response => response.json())
            .then(data => description.html(data.description));
    }
}


function startChallenge(event) {
    event.preventDefault();
    const item = $(event.currentTarget).closest(".accordion-item");
    const module = item.find("#module").val()
    const challenge = item.find("#challenge").val()
    const practice = event.currentTarget.id == "challenge-priv";

    item.find(".challenge-init")
        .addClass("disabled-button")
        .prop("disabled", true);

    var params = {
        "dojo": init.dojo,
        "module": module,
        "challenge": challenge,
        "practice": practice,
    };

    const urlParams = new URLSearchParams(window.location.search);
    let as_user = urlParams.get("as_user");
    if (as_user) {
        params["as_user"] = as_user;
    }

    var result_notification = item.find('#result-notification');
    var result_message = item.find('#result-message');
    result_notification.removeClass('alert-danger');
    result_notification.addClass('alert alert-warning alert-dismissable text-center');
    result_message.html("Loading.");
    result_notification.slideDown();
    var dot_max = 5;
    var dot_counter = 0;
    setTimeout(function loadmsg() {
        if (result_message.html().startsWith("Loading")) {
            if (dot_counter < dot_max - 1){
                result_message.append(".");
                dot_counter++;
            }
            else {
                result_message.html("Loading.");
                dot_counter = 0;
            }
            setTimeout(loadmsg, 500);
        }
    }, 500);

    CTFd.fetch('/pwncollege_api/v1/docker', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(params)
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
        var result_notification = item.find('#result-notification');
        var result_message = item.find('#result-message');

        result_notification.removeClass();

        if (result.success) {
            var message = "Challenge successfully started!";
            result_message.html(message);
            result_notification.addClass('alert alert-info alert-dismissable text-center');

            $(".challenge-active").removeClass("challenge-active");
            item.find(".challenge-name").addClass("challenge-active");
        }
        else {
            var message = "Error:<br><code>" + result.error + "</code><br>"
            result_message.html(message);
            result_notification.addClass('alert alert-warning alert-dismissable text-center');
        }

        result_notification.slideDown();
        item.find(".challenge-init")
            .removeClass("disabled-button")
            .prop("disabled", false);

        $(".challenge-init").removeClass("challenge-hidden");
        $(".challenge-workspace").addClass("challenge-hidden");
        $(".iframe-wrapper").html("");
        if (result.success) {
            item.find(".iframe-wrapper").html("<iframe id=\"workspace-iframe\" class=\"challenge-iframe\" src=\"\" allow=\"clipboard-read *; clipboard-write *\"></iframe>");
            loadWorkspace();
            item.find(".challenge-init").addClass("challenge-hidden");
            item.find(".challenge-workspace").removeClass("challenge-hidden");
            item.find("#workspace-change-privilege")
                .attr("title", practice ? "Restart unprivileged" : "Restart privileged")
                .attr("data-privileged", practice)
                .find(".fas")
                    .toggleClass("fa-lock", !practice)
                    .toggleClass("fa-unlock", practice);
            windowResizeCallback("");
            moduleStartChallenge(event, channel);
        }

        setTimeout(function() {
            item.find(".alert").slideUp();
        }, 60000);
    }).catch(function (error) {
        console.error(error);
        var result_message = item.find('#result-message');
        result_message.html("Submission request failed: " + ((error || {}).message || error));
        result_notification.addClass('alert alert-warning alert-dismissable text-center');
    })
}

async function buildSurvey(item) {
    const form = item.find("form#survey-notification")
    if(form.html() === "") return

    // fix styles
    const challenge_id = item.find('#challenge-id').val()
    for(const style of form.find("style")) {
        let cssText = ""
        for(const rule of style.sheet.cssRules) {
            cssText += ".survey-id-" + challenge_id + " " + rule.cssText + " "
        }
        style.innerHTML = cssText
    }

    const customSubmits = item.find("[data-form-submit]")
    customSubmits.each((_, element) => {
        $(element).click(() => {
            surveySubmit(
                JSON.stringify({
                    response: $(element).attr("data-form-submit")
                }),
                item
            )
            form.slideUp()
        })
    })
    // csrf fix
    const formData = new FormData(form[0])
    form.submit(event => {
        event.preventDefault()
        surveySubmit(JSON.stringify(Object.fromEntries(formData)), item)
        form.slideUp()
    })
}

function surveySubmit(data, item) {
    const challenge_name = item.find('#challenge').val()
    const module_name = item.find('#module').val()
    const dojo_name = init.dojo
    return CTFd.fetch(`/pwncollege_api/v1/dojos/${dojo_name}/${module_name}/${challenge_name}/surveys`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        },
        body: data
    })
}

function markChallengeAsSolved(item) {
    const unsolved_flag = item.find(".challenge-unsolved");
    if (unsolved_flag.hasClass("challenge-solved")) {
        return;
    }

    unsolved_flag.removeClass("challenge-unsolved");
    unsolved_flag.addClass("challenge-solved");

    const total_solves = item.find(".total-solves");
    total_solves.text(
        (parseInt(total_solves.text().trim().split(" ")[0]) + 1) + " solves"
    );

    const answer_input = item.find("#challenge-input");
    answer_input.val("");
    answer_input.removeClass("wrong");
    answer_input.addClass("correct");

    const header = item.find('[id^="challenges-header-"]');
    const current_challenge_id = parseInt(header.attr('id').match(/(\d+)$/)[1]);
    const next_challenge_button = $(`#challenges-header-button-${current_challenge_id + 1}`);

    unlockChallenge(next_challenge_button);
    checkUserAwards()
        .then(handleAwardPopup)
        .catch(error => console.error("Award check failed:", error));
}

var scroll_pos_x;
var scroll_pos_y;

function scrollDisable() {
    scroll_pos_x = window.pageXOffset;
    scroll_pos_y = window.pageYOffset;
    document.body.classList.add("scroll-disabled");
}

function scrollRestore() {
    document.body.classList.remove("scroll-disabled");
    window.pageXOffset = scroll_pos_x;
    window.pageYOffset = scroll_pos_y;
}

function contentExpand(event) {
    $(event.target).closest(".challenge-workspace").addClass("workspace-fullscreen");
    $(".challenge-iframe").addClass("challenge-iframe-fs");
    scrollDisable();
}

function contentContract(event) {
    $(event.target).closest(".challenge-workspace").removeClass("workspace-fullscreen");
    $(".challenge-iframe").removeClass("challenge-iframe-fs");
    scrollRestore();
}

function doFullscreen(event) {
    if ($(".workspace-fullscreen")[0]) {
        contentContract(event);
    }
    else {
        contentExpand(event);
    }
}

function windowResizeCallback(event) {
    $(".challenge-iframe").not(".challenge-iframe-fs").css("aspect-ratio", `${window.innerWidth} / ${window.innerHeight}`);
}

function moduleStartChallenge(event, channel) {
    root = $(event.target).closest(".accordion-item-body").find(".workspace-controls");
    sendChallengeInfo(root, channel);
}

$(() => {
    channel.addEventListener("message", (event) => {
        var challenge_id = event.data["challenge-id"];
        $(".workspace-controls").each((index, item) => {
            item_chal_id = $(item).find("#current-challenge-id").prop("value");
            if (item_chal_id == challenge_id) {
                var priv = $(item).find("#workspace-change-privilege");
                if (priv.length > 0) {
                    priv.attr("data-privileged", event.data["challenge-privilege"]);
                    displayPrivileged({"target": priv[0]}, false);
                }

                selectService($(item).find("#workspace-select").prop("value"), log=false);
            }
        })
    });

    $(".accordion-item").on("show.bs.collapse", function (event) {
        $(event.currentTarget).find("iframe").each(function (i, iframe) {
            if ($(iframe).prop("src"))
                return;
            $(iframe).prop("src", function () {
                return $(this).data("src");
            });
        });
    });

    const broadcast = new BroadcastChannel('broadcast');
    broadcast.onmessage = (event) => {
        if (event.data.msg === 'challengeSolved') {
            const challenge_id = event.data.challenge_id;
            const item = $(`input#challenge-id[value='${challenge_id}']`).closest(".accordion-item");
            if (item.length) {
                markChallengeAsSolved(item);
            }
        }
    };

    var submits = $(".accordion-item").find("#challenge-input");
    for (var i = 0; i < submits.length; i++) {
        submits[i].oninput = submitChallenge;
        submits[i].onkeyup = function (event) {
            if (event.key === "Enter") {
                submitChallenge(event);
            }
        };
    }
    $(".accordion-item").find("#challenge-start").click(startChallenge);
    $(".challenge-init").find("#challenge-priv").click(startChallenge);

    window.addEventListener("resize", windowResizeCallback, true);
    windowResizeCallback("");
    $(".accordion-item").each((_, item) => {
        buildSurvey($(item))
    })
});
