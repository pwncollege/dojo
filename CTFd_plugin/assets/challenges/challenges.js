function submitChallenge(event) {
    event.preventDefault();
    const card = $(event.currentTarget).closest(".card");
    const challenge_id = parseInt(card.find('#challenge-id').val())
    const submission = card.find('#challenge-input').val()

    card.find("#challenge-submit").addClass("disabled-button");
    card.find("#challenge-submit").prop("disabled", true);

    var body = {
        'challenge_id': challenge_id,
        'submission': submission,
    }
    var params = {}

    return CTFd.api.post_challenge_attempt(params, body).then(function (response) {
        return renderSubmissionResponse(response, card);
    })
};

function renderSubmissionResponse(response, card) {
    const result = response.data;

    const result_message = card.find("#result-message");
    const result_notification = card.find("#result-notification");
    const answer_input = card.find("#challenge-input");
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
        }, 3000);
    } else if (result.status === "correct") {
        // Challenge Solved
        result_notification.addClass(
            "alert alert-success alert-dismissable text-center"
        );
        result_notification.slideDown();

        if (
            $(".challenge-solves")
                .text()
                .trim()
        ) {
            // Only try to increment solves if the text isn't hidden
            $(".challenge-solves").text(
                parseInt(
                    $(".challenge-solves")
                        .text()
                        .split(" ")[0]
                ) +
                    1 +
                    " Solves"
            );
        }

        answer_input.val("");
        answer_input.removeClass("wrong");
        answer_input.addClass("correct");
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
        }, 3000);
    }
    setTimeout(function() {
        card.find(".alert").slideUp();
        card.find("#challenge-submit").removeClass("disabled-button");
        card.find("#challenge-submit").prop("disabled", false);
    }, 3000);
}


function startChallenge(event) {
    event.preventDefault();
    const card = $(event.currentTarget).closest(".card");
    const challenge_id = parseInt(card.find('#challenge-id').val())
    const practice = event.currentTarget.id == "challenge-practice";

    $("#challenge-start").addClass("disabled-button");
    $("#challenge-start").prop("disabled", true);
    $("#challenge-practice").addClass("disabled-button");
    $("#challenge-practice").prop("disabled", true);

    var params = {
        'challenge_id': challenge_id,
        'practice': practice,
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
        var result_notification = card.find('#result-notification');
        var result_message = card.find('#result-message');

        result_notification.removeClass();

        if (result.success) {
            var message = "Challenge successfully started!";
            result_message.html(message);
            result_notification.addClass('alert alert-info alert-dismissable text-center');

            $(".challenge-active").removeClass("challenge-active");
            card.find(".challenge-name").addClass("challenge-active");
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

        setTimeout(function() {
            $("#challenge-start").removeClass("disabled-button");
            $("#challenge-start").prop("disabled", false);
            $("#challenge-practice").removeClass("disabled-button");
            $("#challenge-practice").prop("disabled", false);

            card.find(".alert").slideUp();
            card.find("#challenge-submit").removeClass("disabled-button");
            card.find("#challenge-submit").prop("disabled", false);
        }, 3000);
    });
}


$(() => {
    $(".lecture").on("show.bs.collapse", function (event) {
        $(event.currentTarget).find("iframe").each(function (i, iframe) {
            if ($(iframe).prop("src"))
                return;
            $(iframe).prop("src", function () {
                return $(this).data("src");
            });
        });
    });

    $("#challenge-input").keyup(function(event) {
        if (event.keyCode == 13) {
            $("#challenge-submit").click();
        }
    });

    $(".card").find("#challenge-submit").click(submitChallenge);
    $(".card").find("#challenge-start").click(startChallenge);
    $(".card").find("#challenge-practice").click(startChallenge);
});
