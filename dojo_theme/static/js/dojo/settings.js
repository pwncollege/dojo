var error_template =
    '<div class="alert alert-danger alert-dismissable" role="alert">\n' +
    '  <span class="sr-only">Error:</span>\n' +
    '  <span id="message"></span>' +
    '  <button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button>\n' +
    '</div>';

var success_template =
    '<div class="alert alert-success alert-dismissable submit-row" role="alert">\n' +
    '  <strong>Success!</strong>\n' +
    '  <span id="message"></span>' +
    '  <button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button>\n' +
    '</div>';

$(() => {
    const keyForm = $("#key-form");
    const keyResults = $("#key-results");
    keyForm.submit(e => {
        e.preventDefault();
        keyResults.empty();
        const params = keyForm.serializeJSON();

        CTFd.fetch("/pwncollege_api/v1/ssh_key", {
            method: "PATCH",
            credentials: "same-origin",
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json"
            },
            body: JSON.stringify(params)
        }).then(response => {
            return response.json()
        }).then(result => {
            if (result.success) {
                keyResults.html(success_template);
                keyResults.find("#message").text("Your public key has been updated");
            } else {
                keyResults.html(error_template);
                keyResults.find("#message").html(result.error);
            }
        });
    });

    const privateDojoResults = $("#private-dojo-results");
    function dojoForm(form, endpoint, confirmation_msg, success) {
        form.submit((e) => {
            if (confirmation_msg && !confirm(confirmation_msg)) return;

            e.preventDefault();
            privateDojoResults.empty();
            const params = form.serializeJSON();
            CTFd.fetch(`/pwncollege_api/v1/private_dojo/${endpoint}`, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(params)
            }).then(response => {
                return response.json()
            }).then(result => {
                if (result.success) {
                    privateDojoResults.html(success_template);
                    privateDojoResults.find("#message").html(success(result));
                } else {
                    privateDojoResults.html(error_template);
                    privateDojoResults.find("#message").html(result.error);
                }
            });
        });
    }

    const privateDojoEnterForm = $("#private-dojo-enter-form");
    const privateDojoJoinForm = $("#private-dojo-join-form");
    const privateDojoInitializeForm = $("#private-dojo-initialize-form");
    const privateDojoCreateForm = $("#private-dojo-create-form");

    dojoForm(privateDojoEnterForm, "activate", false, result => {
        return "Dojo successfully entered";
    });
    dojoForm(privateDojoJoinForm, "join", false, result => {
        return "Dojo successfully joined";
    });
    dojoForm(privateDojoInitializeForm, "initialize", false, result => {
        $("#initialize-code").val(result.join_code);
        return "Dojo successfully initialized";
    });
    dojoForm(privateDojoCreateForm, "create", false, result => {
        return "Repository for dojo '" + result.dojo_id + "' successfully created! Logs:<br>" + result.load_logs;
    });
});
