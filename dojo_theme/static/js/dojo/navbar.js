async function fetch_current_module() {
    const response = await fetch('/active-module/');
    const data = await response.json();
    if (data.challenge_id) {
        $("#challengeMenuButton").removeClass("d-none");
    }
    else {
        $("#challengeMenuButton").addClass("d-none");
    }
    return data
};
async function updateNavbarDropdown() {
    const data = await fetch_current_module();

    const html_template = `
       
        <div class="nav-link text-nowrap text-center px-4">
            <a class="d-none d-md-inline" href="/${data.c_current.dojo_reference_id}/">${data.c_current.dojo_name}</a>
            <span class="d-none d-md-inline mx-1">/</span>
            <a class="d-none d-lg-inline" href="/${data.c_current.dojo_reference_id}/${data.c_current.module_id}/">
            ${data.c_current.module_name}
            </a>
            <span class="d-none d-lg-inline mx-1">/</span>
            <span>${data.c_current.challenge_name}</span>
        </div>
        <div class="dropdown-divider"></div>
       
        <div class="container-fluid">
            <div class="row mt-3">
                <div class="col-md-8 form-group">
                    <input id="dropdown-challenge-input" class="challenge-input form-control" type="text" name="answer" placeholder="Flag">
                </div>
                <div class="col form-group">
                    <button id="dropdown-challenge-submit" type="submit" class="challenge-submit btn btn-sm btn-outline-secondary float-right w-100 h-100">
                            Submit
                    </button>
                </div>
            </div>  
        </div>
        <div class="container-fluid">
            <div class="row pb-2">
                <div class="col overflow-hidden">
                    <button class="btn btn-dark  text-truncate w-100" href="#">
                    <i class="fas fa-backward"></i>
                     <span class="d-none d-sm-inline">${data.c_previous.challenge_name}</span>
                     <span class="d-inline d-sm-none">Previous</span>
                    </button>
                </div>  
                <div class="col-4 col-lg-3 ">  
                    <button class="btn btn-dark px-2 text-truncate w-100" href="#">
                    
                    <i class="fas fa-redo-alt"></i>
                    Restart
                    </button>
                </div>  
                <div class="col overflow-hidden">      
                    <button class="btn btn-dark text-truncate w-100" href="#">
                    <i class="fas fa-forward"></i>
                    <span class="d-none d-sm-inline" >${data.c_next.challenge_name}</span>
                    <span class="d-inline d-sm-none">Next</span>
                    </button>
                </div>
            </div>
        </div>
    `;
   // $("#navbar_dropdown").html(html_template);
    //Dropdown Top
    $("#dropdown-dojo").text(data.c_current.dojo_name);
    $("#dropdown-dojo").attr("href", `/${data.c_current.dojo_reference_id}/`);
    $("#dropdown-module").text(data.c_current.module_name);
    $("#dropdown-module").attr("href", `/${data.c_current.dojo_reference_id}/${data.c_current.module_id}/`);
    $("#dropdown-challenge").text(data.c_current.challenge_name);

    //Dropdown Down
    $("#dropdown-prev-name").text(data.c_previous.challenge_name);
    $("#previous #dojo").val(data.c_previous.dojo_reference_id);
    $("#previous #module").val(data.c_previous.module_id);
    $("#previous #challenge").val(data.c_previous.challenge_reference_id);
    $("#previous #challenge-id").val(data.c_previous.challenge_id);

    //current
    $("#current #dojo").val(data.c_current.dojo_reference_id);
    $("#current #module").val(data.c_current.module_id);
    $("#current #challenge").val(data.c_current.challenge_reference_id);
    $("#current #challenge-id").val(data.c_current.challenge_id);


    $("#dropdown-next-name").text(data.c_next.challenge_name);
    $("#next #dojo").val(data.c_next.dojo_reference_id);
    $("#next #module").val(data.c_next.module_id);
    $("#next #challenge").val(data.c_next.challenge_reference_id);
    $("#next #challenge-id").val(data.c_next.challenge_id);
}

function DropdownStartChallenge(event) {
    event.preventDefault();
    const item = $(event.currentTarget).closest(".overflow-hidden");
    const module = item.find("#module").val()
    const challenge = item.find("#challenge").val()
    const dojo = item.find("#dojo").val()
    $("#dropdown-controls").find("button").prop("disabled", true);

    var params = {
        "dojo": dojo,
        "module": module,
        "challenge": challenge,
        "practice": false,
    };

    var result_notification = $("#dropdown-controls").find('#result-notification');
    var result_message = $("#dropdown-controls").find('#result-message');
    result_notification.removeClass('alert-danger');
    result_notification.addClass('alert alert-warning alert-dismissable text-center');
    result_message.html("Loading.");
    result_notification.slideDown();
    setTimeout(function loadmsg() {
        if (result_message.html().startsWith("Loading")) {
            result_message.append(".");
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
    }).then(async function (result) {
        let result_notification = $("#dropdown-controls").find('#result-notification');
        let result_message = $("#dropdown-controls").find('#result-message');

        result_notification.removeClass();

        if (result.success) {
            let message = `Challenge successfully started! You can interact with it through a <a href="/workspace/vscode">VSCode Workspace</a> or a <a href="/workspace/desktop">GUI Desktop</a>.`;
            result_message.html(message);
            result_notification.addClass('alert alert-info alert-dismissable text-center');
            await updateNavbarDropdown();
        }
        else {
            let message = "Error:";
            message += "<br>";
            message += "<code>" + result.error + "</code>";
            message += "<br>";
            result_message.html(message);
            result_notification.addClass('alert alert-warning alert-dismissable text-center');
        }

        result_notification.slideDown();

        setTimeout(function() {
            $("#dropdown-controls").find("button").prop("disabled", false);
            $("#dropdown-controls").find(".alert").slideUp();
            item.find("#challenge-submit").removeClass("disabled-button");
            item.find("#challenge-submit").prop("disabled", false);
        }, 10000);
    }).catch(function (error) {
        console.error(error);
        let result_message = $("#dropdown-controls").find('#result-message');
        result_message.html("Submission request failed: " + ((error || {}).message || error));
        result_notification.addClass('alert alert-warning alert-dismissable text-center');
    })
    event.stopPropagation();
}

function submitFlag(event) {
    event.preventDefault();
    const challenge_id = $("#current").find("#challenge-id").val()
    const submission = $("#dropdown-challenge-input").val()

    var body = {
        'challenge_id': challenge_id,
        'submission': submission,
    }
    var result_notification = $("#dropdown-controls").find('#result-notification');
    var result_message = $("#dropdown-controls").find('#result-message');
    result_notification.removeClass();
    result_notification.addClass('alert alert-warning alert-dismissable text-center');
    result_message.html("Loading...");
    result_notification.slideDown();

    CTFd.api.post_challenge_attempt({}, body).then(function (resp) {
        const result = resp.data;
        console.log('Submit Flag result', result);

        if (result.status === 'correct') {
            result_notification.removeClass();
            result_notification.addClass('alert alert-success alert-dismissable text-center');
            result_message.html('Flag submitted successfully!');
            $("#dropdown-challenge-input").val("")
        } else {
            result_notification.removeClass();
            result_notification.addClass('alert alert-danger alert-dismissable text-center');
            result_message.html('Flag submission failed:'+ result.message);
        }
        setTimeout(() => result_notification.slideUp(), 5000);
    });
    event.stopPropagation();
}
updateNavbarDropdown()
$(() => {
  $(".close-link").on("click", () => {
    $(".navbar")
      .addClass("navbar-hiding")
      .one("animationend webkitAnimationEnd oAnimationEnd MSAnimationEnd", () => {
        $(".navbar").removeClass("navbar-hiding").addClass("navbar-hidden");
        $("main").addClass("main-navbar-hidden");
        $(".navbar-pulldown").addClass("navbar-pulldown-shown");
      });
  });
  $(".navbar-pulldown").on("click", () => {
    $(".navbar")
      .removeClass("navbar-hiding")
      .removeClass("navbar-hidden");
    $("main").removeClass("main-navbar-hidden");
    $(".navbar-pulldown").removeClass("navbar-pulldown-shown");
  });
  $("#SubmitFlagButton").on("click", async () => {
      const active_module_data = await fetch_current_module();
      const submission = prompt(`${active_module_data.dojo_name}\n` +
      `${active_module_data.module_name} => ` +
          `${active_module_data.challenge_name}\n` +
          `Please enter the flag to submit:`, 'Flag...'
      );
      const body = {
          'challenge_id': active_module_data.challenge_id,
          'submission': submission,
      }
      const result = await CTFd.api.post_challenge_attempt({}, body).then( (resp) => { return resp.data })

      console.log('Submit Flag result', result);
      console.log('Submit Flag button clicked', submission);
  });
    $("#previous").find("#challenge-start").click(DropdownStartChallenge);
    $("#current").find("#challenge-start").click(DropdownStartChallenge);
    $("#next").find("#challenge-start").click(DropdownStartChallenge);
    $("#dropdown-challenge-submit").click(submitFlag);
    $("#dropdown-challenge-input").keyup(function (event) {
        if (event.keyCode == 13) {
            $("#dropdown-challenge-submit").click();
        }
    });
    $("#navbarDropdown").click(updateNavbarDropdown);
});
