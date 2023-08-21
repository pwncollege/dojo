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

function form_fetch_and_show(name, endpoint, method, success_message) {
    const form = $(`#${name}-form`);
    const results = $(`#${name}-results`);
    form.submit(e => {
        e.preventDefault();
        results.empty();
        const params = form.serializeJSON();

        CTFd.fetch(endpoint, {
            method: method,
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
                results.html(success_template);
                results.find("#message").text(success_message);
            } else {
                results.html(error_template);
                results.find("#message").html(result.error);
            }
        });
    });
}

$(() => {
    form_fetch_and_show("identity", `/dojo/${init.dojo}/course/identity`, "PATCH", "Your identity has been updated");
});