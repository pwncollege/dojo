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

function form_fetch_and_show(name, endpoint, method, success_message, confirm_msg=null) {
    const form = $(`#${name}-form`);
    const results = $(`#${name}-results`);
    form.submit(e => {
        e.preventDefault();
        results.empty();
        const params = form.serializeJSON();
        if (confirm_msg && !confirm(confirm_msg(form, params))) return;
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

function button_fetch_and_show(name, endpoint, method,data, success_message, abort_message, confirm_msg=null) {
    const button = $(`#${name}-button`);
    const results = $(`#${name}-results`);

    button.click(()=>{
        results.empty();
        if (confirm_msg && !confirm_msg(data)) {
            results.html(error_template);
            results.find("#message").html(abort_message);
            return
        };
        CTFd.fetch(endpoint, {
            method: method,
            credentials: "same-origin",
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json"
            },
            body: JSON.stringify(data)
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
    form_fetch_and_show("ssh-key", "/pwncollege_api/v1/ssh_key", "POST", "Your public key has been updated");
    form_fetch_and_show("discord", "/pwncollege_api/v1/discord", "DELETE", "Your discord account has been disconnected");
    form_fetch_and_show("dojo-create", "/pwncollege_api/v1/dojo/create", "POST", "Your dojo has been created");
    form_fetch_and_show("dojo-promote-admin", `/pwncollege_api/v1/dojo/${init.dojo}/promote-admin`, "POST", "User has been promoted to admin.", confirm_msg = (form, params) => {
        var user_name = form.find(`#name-for-${params["user_id"]}`)
        return `Promote ${user_name.text()} (UID ${params["user_id"]}) to admin?`;
    });
    form_fetch_and_show("dojo-promote-dojo", `/pwncollege_api/v1/dojo/${init.dojo}/promote-dojo`, "POST", "Dojo has been made official!", confirm_msg = (form, params) => {
        return "Make this dojo official? Official dojos are accessible by their ID, without the hex differentiator, and show up in more dojo listings.";
    });
    form_fetch_and_show("dojo-award-prune", `/pwncollege_api/v1/dojo/${init.dojo}/prune-awards`, "POST", "Legacy awards have been pruned.", confirm_msg = (form, params) => {
        return `Prune all awarded emoji based on updated completion requirements?`;
    });
    button_fetch_and_show("dojo-delete",  `/dojo/${init.dojo}/delete/`, "POST", {dojo: init.dojo} ,"Dojo has been deleted.", "Deletion has been canceled.", confirm_msg = (x)=> {
        var confirmation = prompt(`Are you sure you want to delete the dojo?\nEnter the dojo name\n\n${x.dojo}\n\nto confirm this action.\nThis action cannot be undone.`);
        return confirmation === x.dojo
    });
    $(".copy-button").click((event) => {
        let input = $(event.target).parents(".input-group").children("input")[0];
        input.select();
        input.setSelectionRange(0, 128);
        navigator.clipboard.writeText(input.value);

        $(event.target).tooltip({
            title: "Copied!",
            trigger: "manual"
        });
        $(event.target).tooltip("show");

        setTimeout(function() {
            $(event.target).tooltip("hide");
        }, 1500);
    })
});
