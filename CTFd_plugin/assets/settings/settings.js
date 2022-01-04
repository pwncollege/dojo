var error_template =
    '<div class="alert alert-danger alert-dismissable" role="alert">\n' +
    '  <span class="sr-only">Error:</span>\n' +
    "  {0}\n" +
    '  <button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button>\n' +
    "</div>";

var success_template =
    '<div class="alert alert-success alert-dismissable submit-row" role="alert">\n' +
    "  <strong>Success!</strong>\n" +
    "   {0}\n" +
    '  <button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button>\n' +
    "</div>";

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
                keyResults.html(success_template.format("Your public key has been updated"));
            } else {
                result.keys(result.errors).map((error) => {
                    const input = $(keyForm.find("input[name={0}]".format(error)));
                    input.addClass("input-filled-invalid");
                    input.removeClass("input-filled-valid");
                    keyResults.append(error_template.format(result.errors[error]));
                });
            }
        });
    });

    const privateDojoResults = $("#private-dojo-results");
    function initializePrivateDojoForm(form, endpoint, success) {
        form.submit((e) => {
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
                    privateDojoResults.html(success_template.format(success(result)));
                } else {
                    privateDojoResults.html(error_template.format(result.error));
                }
            });
        });
    }

    const privateDojoEnterForm = $("#private-dojo-enter-form");
    const privateDojoJoinForm = $("#private-dojo-join-form");
    const privateDojoInitializeForm = $("#private-dojo-initialize-form");

    initializePrivateDojoForm(privateDojoEnterForm, "activate", result => {
        return "Dojo successfully entered";
    });
    initializePrivateDojoForm(privateDojoJoinForm, "join", result => {
        return "Dojo successfully joined";
    });
    initializePrivateDojoForm(privateDojoInitializeForm, "initialize", result => {
        $("#initialize-code").val(result.code);
        return "Dojo successfully initialized";
    });
});
