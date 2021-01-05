CTFd._internal.challenge.data = undefined

CTFd._internal.challenge.renderer = CTFd.lib.markdown();

CTFd._internal.challenge.preRender = function () { }

CTFd._internal.challenge.render = function (markdown) {
    return CTFd._internal.challenge.renderer.render(markdown)
}

CTFd._internal.challenge.postRender = function () { }

CTFd._internal.challenge.submit = function (preview) {
    var challenge_id = parseInt(CTFd.lib.$('#challenge-id').val())
    var submission = CTFd.lib.$('#challenge-input').val()

    var body = {
        'challenge_id': challenge_id,
        'submission': submission,
    }
    var params = {}
    if (preview) {
        params['preview'] = true
    }

    return CTFd.api.post_challenge_attempt(params, body).then(function (response) {
        if (response.status === 429) {
            // User was ratelimited but process response
            return response
        }
        if (response.status === 403) {
            // User is not logged in or CTF is paused.
            return response
        }
        return response
    })
};

function workon(challenge_id, practice=false) {
    var element = practice ? $('#practice > i') : $('#workon > i');
    element.addClass('animate-flicker');

    var selected_path = $('#selected-path').val() || "";
    var params = {
        'challenge_id': challenge_id,
        'practice': practice,
        'selected_path': selected_path
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
        return response.json();
    }).then(function (result) {
        var result_notification = $('#result-notification');
        var result_message = $('#result-message');

        result_notification.removeClass();

        element.removeClass('animate-flicker');

        if (result.success) {
            var message = "";
            message += "You can connect with:";
            message += "<br>";
            message += "<code>" + result.ssh + "</code>";
            message += "<br>";
            message += "Authenticate with your private key (<code>-i</code>)";
            result_message.html(message);
            result_notification.addClass('alert alert-info alert-dismissable text-center');
        }
        else {
            result_message.html(result.error);
            result_notification.addClass('alert alert-warning alert-dismissable text-center');
        }

        result_notification.slideDown();
    });
}

function download(challenge_id) {
    const token = btoa(JSON.stringify({'challenge_id': challenge_id}));
    window.location.pathname = '/download/' + token;
}

function inspect(challenge_id) {
    var element = $('#inspect > i');
    element.addClass('animate-flicker');

    var params = {'challenge_id': challenge_id};

    CTFd.fetch('/pwncollege_api/v1/binary_ninja/generate', {
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
        var result_notification = $('#result-notification');
        var result_message = $('#result-message');

        result_notification.removeClass();

        element.removeClass('animate-flicker');

        if (result.success) {
            window.open(result.url);
        }
        else {
            result_message.html(result.error);
            result_notification.addClass('alert alert-warning alert-dismissable text-center');
        }

        result_notification.slideDown();
    });
}

function render_multi_solved(category) {
    CTFd.fetch('/pwncollege_api/v1/user_flag/multi_solved/' + category, {
        method: 'GET',
        credentials: 'same-origin',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
    }).then(function (response) {
        return response.json();
    }).then(function (result) {
        if (result.success) {
            $('#multi-solved-body').empty();
            result.solved.forEach((solved) => {
                $('#multi-solved-body').append($("<tr>").append($("<td>").text(solved)));
            });
        }
    });
}
