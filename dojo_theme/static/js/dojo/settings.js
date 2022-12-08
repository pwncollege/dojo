var error_template =
    '<div class="alert alert-danger alert-dismissable" role="alert">\n' +
    '  <span class="sr-only">Error:</span>\n' +
    '  <span id="message"></span>' +
    '  <button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button>\n' +
    '</div>';

var success_template =
    '<div class="alert alert-success alert-dismissable submit-row" role="alert">\n' +
    '  <p><strong>Success!</strong>\n' +
    '  <span id="message"></span></p>' +
    '  <button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button>\n' +
    '  <p><strong>Note!</strong> You might need to refresh this page to observe the effects of this action.</p>' +
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
            e.preventDefault();
            privateDojoResults.html(error_template);
            privateDojoResults.find("#message").html("Loading...");
            if (confirmation_msg && !confirm(confirmation_msg)) return;

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

    const privateDojoJoinForm = $("#private-dojo-join-form");
    const privateDojoCreateForm = $("#private-dojo-create-form");
    const privateDojoDeleteForm = $("#private-dojo-delete-form");
    const privateDojoUpdateForm = $("#private-dojo-update-form");
    const privateDojoRandomizeForm = $("#private-dojo-randomize-form");
    const privateDojoPublicizeForm = $("#private-dojo-publicize-form");

    dojoForm(privateDojoJoinForm, "join", false, result => {
        return "Dojo successfully joined";
    });
    dojoForm(privateDojoCreateForm, "create", false, result => {
        return "Dojo '" + result.dojo_id + "' successfully created! Logs:<br>" + result.load_logs;
    });
    dojoForm(privateDojoUpdateForm, "create", false, result => {
        return "Dojo '" + result.dojo_id + "' successfully updated! Logs:<br>" + result.load_logs;
    });
    dojoForm(privateDojoRandomizeForm, "change-join-code", "You are about to set a random join code for your dojo. If the dojo was public, it will become private and only people who had joined with a join code will retain access to it. If the dojo is already private, the old code will no longer be valid but students who previously joined will remain in the dojo.", result => {
        return "Dojo '" + result.dojo_id + "' join code rerandomized to <code>" + result.join_code + "</code>!";
    });
    dojoForm(privateDojoPublicizeForm, "make-public", "You are about to make this dojo public, open for anyone to access!", result => {
        return "Dojo '" + result.dojo_id + "' made public!";
    });
    dojoForm(privateDojoDeleteForm, "delete", "You are about to delete this dojo. This action cannot be undone.", result => {
        return "Dojo '" + result.dojo_id + "' deleted!";
    });
});
