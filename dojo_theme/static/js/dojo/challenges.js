function submitChallenge(event) {
    event.preventDefault();
    const item = $(event.currentTarget).closest(".accordion-item");
    const challenge_id = parseInt(item.find('#challenge-id').val())
    const submission = item.find('#challenge-input').val()

    item.find("#challenge-submit").addClass("disabled-button");
    item.find("#challenge-submit").prop("disabled", true);

    var body = {
        'challenge_id': challenge_id,
        'submission': submission,
    }
    var params = {}

    if (submission == "pwn.college{practice}") {
        return renderSubmissionResponse({ "data": { "status": "practice", "message": "You have submitted the \"practice\" flag from launching the challenge in Practice mode! This flag is not valid for scoring. Run the challenge in non-practice mode by pressing Start above, then use your solution to get the \"real\" flag and submit it!" } }, item);
    }
    return CTFd.api.post_challenge_attempt(params, body).then(function (response) {
        return renderSubmissionResponse(response, item);
    })
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
            if(data.type === "thumb") {
                survey_notification.addClass("text-center")
            } else {
                survey_notification.addClass("text-left")
            }
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
        item.find("#challenge-submit").removeClass("disabled-button");
        item.find("#challenge-submit").prop("disabled", false);
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
    const practice = event.currentTarget.id == "challenge-practice";

    item.find("#challenge-start").addClass("disabled-button");
    item.find("#challenge-start").prop("disabled", true);
    item.find("#challenge-practice").addClass("disabled-button");
    item.find("#challenge-practice").prop("disabled", true);

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
            var message = `Challenge successfully started! You can interact with it through a <a href="/workspace/code" target="dojo_workspace">VSCode Workspace</a> or a <a href="/workspace/desktop" target="dojo_workspace">GUI Desktop Workspace</a>.`;
            result_message.html(message);
            result_notification.addClass('alert alert-info alert-dismissable text-center');

            $(".challenge-active").removeClass("challenge-active");
            item.find(".challenge-name").addClass("challenge-active");
            setTimeout(() => updateNavbarDropdown(), 1000);
        }
        else {
            var message = "";
            message += "Error:";
            message += "<br>";
            message += "<code>" + result.error + "</code>";
            message += "<br>";
            result_message.html(message);
            result_notification.addClass('alert alert-warning alert-dismissable text-center');
        }

        result_notification.slideDown();
        item.find("#challenge-start").removeClass("disabled-button");
        item.find("#challenge-start").prop("disabled", false);
        item.find("#challenge-practice").removeClass("disabled-button");
        item.find("#challenge-practice").prop("disabled", false);

        setTimeout(function() {
            item.find(".alert").slideUp();
            item.find("#challenge-submit").removeClass("disabled-button");
            item.find("#challenge-submit").prop("disabled", false);
        }, 60000);
    }).catch(function (error) {
        console.error(error);
        var result_message = item.find('#result-message');
        result_message.html("Submission request failed: " + ((error || {}).message || error));
        result_notification.addClass('alert alert-warning alert-dismissable text-center');
    })
}

function clickSurveyThumb(event) {
    const clicked = $(event.currentTarget)
    const item = $(event.currentTarget).closest(".accordion-item")
    const survey_notification = item.find("#survey-notification")
    if(clicked.hasClass("fa-thumbs-up")) {
        surveySubmit("up", item)
    } else {
        surveySubmit("down", item)
    }
    survey_notification.slideUp()
}

function clickSurveyOption(event) {
    const clicked = $(event.currentTarget)
    const item = $(event.currentTarget).closest(".accordion-item")
    const survey_notification = item.find("#survey-notification")
    const index = clicked.attr("data-id")
    surveySubmit(parseInt(index), item)
    survey_notification.slideUp()
}

function clickSurveySubmit(event) {
    const item = $(event.currentTarget).closest(".accordion-item")
    const survey_notification = item.find("#survey-notification")
    const response = item.find("#survey-freeresponse-input").val()
    surveySubmit(response, item)
    survey_notification.slideUp()
}

function surveySubmit(data, item) {
    const challenge_name = item.find('#challenge').val()
    const module_name = item.find('#module').val()
    const dojo_name = init.dojo
    return CTFd.fetch(`/pwncollege_api/v1/dojos/${dojo_name}/surveys/${module_name}/${challenge_name}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            response: data
        })
    })
}


$(() => {
    $(".accordion-item").on("show.bs.collapse", function (event) {
        $(event.currentTarget).find("iframe").each(function (i, iframe) {
            if ($(iframe).prop("src"))
                return;
            $(iframe).prop("src", function () {
                return $(this).data("src");
            });
        });
    });

    $(".challenge-input").keyup(function (event) {
        if (event.keyCode == 13) {
            const submit = $(event.currentTarget).closest(".accordion-item").find("#challenge-submit");
            submit.click();
        }
    });

    $(".accordion-item").find("#challenge-submit").click(submitChallenge);
    $(".accordion-item").find("#challenge-start").click(startChallenge);
    $(".accordion-item").find("#challenge-practice").click(startChallenge);

    $(".accordion-item").find("#survey-thumbs-up").click(clickSurveyThumb)
    $(".accordion-item").find("#survey-thumbs-down").click(clickSurveyThumb)

    $(".accordion-item").find(".survey-option").click(clickSurveyOption)

    $(".accordion-item").find("#survey-submit").click(clickSurveySubmit)
});
