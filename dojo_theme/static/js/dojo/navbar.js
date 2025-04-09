const broadcast = new BroadcastChannel('broadcast');

broadcast.onmessage = (event) => {
    if (event.data.msg === 'New challenge started') {
        if (window.location.pathname === '/workspace/code') {
            window.location.reload();
        }
        else if (window.location.pathname === '/workspace/desktop') {
            get_and_set_iframe_url()
        }
    }
};
function get_and_set_iframe_url() {
    // check if the window location pathname starts with /workspace/ and set the rest of the path as an variable service
    const service = window.location.pathname.startsWith('/workspace/') ? window.location.pathname.substring(11) : '';
    fetch("/pwncollege_api/v1/workspace?service=" + service)
        .then(response => response.json())
        .then(data => {
            if (data.active) {
                const iframe = $("#workspace_iframe")[0];
                if (iframe.src !== window.location.origin + data.iframe_src) {
                    iframe.src = data.iframe_src;
                }
            }
        });
}
async function fetch_current_module() {
    const response = await fetch('/active-module/');
    const data = await response.json();
    if (data.c_current) {
        $("#challengeMenuButton").removeClass("d-none");
    }
    else {
        $("#challengeMenuButton").addClass("d-none");
    }
    return data
}
async function updateNavbarDropdown() {
    const data = await fetch_current_module();

    if (data.c_current) {
        $("#dropdown-dojo").text(data.c_current.dojo_name).attr("href", `/${data.c_current.dojo_reference_id}/`);
        $("#dropdown-module").text(data.c_current.module_name).attr("href", `/${data.c_current.dojo_reference_id}/${data.c_current.module_id}/`);
        $("#dropdown-challenge").text(data.c_current.challenge_name);
        $("#current #dojo").val(data.c_current.dojo_reference_id);
        $("#current #module").val(data.c_current.module_id);
        $("#current #challenge").val(data.c_current.challenge_reference_id);
        $("#current #challenge-id").val(data.c_current.challenge_id);
        $("#dropdown-description").html(data.c_current.description);

        if ("dojo_name" in data.c_previous) {
            $("#previous").removeClass("invisible");
            $("#dropdown-prev-name").text(data.c_previous.challenge_name);
            $("#previous #dojo").val(data.c_previous.dojo_reference_id);
            $("#previous #module").val(data.c_previous.module_id);
            $("#previous #challenge").val(data.c_previous.challenge_reference_id);
            $("#previous #challenge-id").val(data.c_previous.challenge_id);
        } else {
            $("#previous").addClass("invisible");
        }
        if ("dojo_name" in data.c_next) {
            $("#next").removeClass("invisible");
            $("#dropdown-next-name").text(data.c_next.challenge_name);
            $("#next #dojo").val(data.c_next.dojo_reference_id);
            $("#next #module").val(data.c_next.module_id);
            $("#next #challenge").val(data.c_next.challenge_reference_id);
            $("#next #challenge-id").val(data.c_next.challenge_id);
        } else {
            $("#next").addClass("invisible");
        }
    }
}

function DropdownStartChallenge(event) {
    event.preventDefault();
    const item = $(event.currentTarget).closest(".overflow-hidden");
    const module = item.find("#module").val()
    const challenge = item.find("#challenge").val()
    const dojo = item.find("#dojo").val()
    const dropdown_controls = $("#dropdown-controls");
    dropdown_controls.find("button").prop("disabled", true);

    var params = {
        "dojo": dojo,
        "module": module,
        "challenge": challenge,
        "practice": false,
    };

    var result_notification = dropdown_controls.find('#result-notification');
    var result_message = dropdown_controls.find('#result-message');
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
    }).then(async function (result) {
        let result_notification = dropdown_controls.find('#result-notification');
        let result_message = dropdown_controls.find('#result-message');

        result_notification.removeClass();

        if (result.success) {
            let message = `Challenge successfully started! You can interact with it through a <a href="/workspace/code" target="dojo_workspace">VSCode Workspace</a> or a <a href="/workspace/desktop">GUI Desktop</a>.`;
            result_message.html(message);
            result_notification.addClass('alert alert-info alert-dismissable text-center');
            await updateNavbarDropdown();
            $(".challenge-active").removeClass("challenge-active");
            $(`.accordion-item input[value=${params.challenge}]`).closest(".accordion-item").find("h4.challenge-name").addClass("challenge-active");
           const broadcast_send = new BroadcastChannel('broadcast');
            broadcast_send.postMessage({
               time: new Date().getTime(),
               msg: 'New challenge started'
           });
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
            dropdown_controls.find("button").prop("disabled", false);
            dropdown_controls.find(".alert").slideUp();
            item.find("#challenge-submit").removeClass("disabled-button");
            item.find("#challenge-submit").prop("disabled", false);
        }, 10000);
    }).catch(function (error) {
        console.error(error);
        let result_message = dropdown_controls.find('#result-message');
        result_message.html("Submission request failed: " + ((error || {}).message || error));
        result_notification.addClass('alert alert-warning alert-dismissable text-center');
    })
    event.stopPropagation();
}

function submitFlag(event) {
    event.preventDefault();
    const challenge_id = $("#current").find("#challenge-id").val();
    const submission = $("#dropdown-challenge-input").val();
    const dropdown_controls = $("#dropdown-controls");
    var body = {
        'challenge_id': challenge_id,
        'submission': submission,
    };
    var result_notification = dropdown_controls.find('#result-notification');
    var result_message = dropdown_controls.find('#result-message');
    result_notification.removeClass();
    result_notification.addClass('alert alert-warning alert-dismissable text-center');
    result_message.html("Loading...");
    result_notification.slideDown();
    if (submission === "pwn.college{practice}") {
        result_notification.removeClass();
        result_notification.addClass('alert alert-success alert-dismissable text-center');
        result_message.html('You have submitted the \"practice\" flag from launching the challenge in Practice mode! This flag is not valid for scoring. Run the challenge in non-practice mode by pressing Start above, then use your solution to get the \"real\" flag and submit it!');
        setTimeout(() => result_notification.slideUp(), 5000);
        event.stopPropagation();
        return
    }

    CTFd.api.post_challenge_attempt({}, body).then(function (resp) {
        const result = resp.data;
        if (result.status === 'correct') {
            result_notification.removeClass();
            result_notification.addClass('alert alert-success alert-dismissable text-center');
            result_message.html('Flag submitted successfully!');
            $("#dropdown-challenge-input").val("");
        } else {
            result_notification.removeClass();
            result_notification.addClass('alert alert-danger alert-dismissable text-center');
            result_message.html('Flag submission failed: '+ result.message);
        }
        setTimeout(() => result_notification.slideUp(), 5000);
    });
    event.stopPropagation();
}
updateNavbarDropdown();
$(() => {
    $("#show_description").click((event) =>{
        $("#dropdown-description").toggle();
        event.stopPropagation();
    });
    $("#dropdown-description").click((event) =>{
        event.stopPropagation();
    });
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
    $("#previous").find("#challenge-start").click(DropdownStartChallenge);
    $("#current").find("#challenge-start").click(DropdownStartChallenge);
    $("#next").find("#challenge-start").click(DropdownStartChallenge);
    $("#dropdown-challenge-submit").click(submitFlag);
    $("#dropdown-challenge-input").keyup(function (event) {
        if (event.keyCode === 13) {
            $("#dropdown-challenge-submit").click();
        }
    });
    $("#navbarDropdown").click(updateNavbarDropdown);
});


document.addEventListener('DOMContentLoaded', function () {
    const searchNavItem = document.querySelector('a.nav-link[href="#"] i.fa-search')?.closest('a');
    if (searchNavItem) {
        searchNavItem.addEventListener('click', function (e) {
        e.preventDefault();
        $('#searchModal').modal('show').on('shown.bs.modal', function () {
            document.getElementById('searchInput').focus();
            });
        });
    }

    document.getElementById('searchCloseBtn')?.addEventListener('click', () => {
        $('#searchModal').modal('hide');
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
            $('#searchModal').modal('hide');
        }
    });
});

$('#searchModal').on('hidden.bs.modal', function () {
    document.getElementById('searchInput').value = '';
    document.getElementById('searchResults').innerHTML = '';
    clearNavigationState();
});
  
const input = document.getElementById("searchInput");
const resultsEl = document.getElementById("searchResults");

let activeIndex = -1;
let resultItems = [];
let suppressScroll = false;

function renderSkeleton(count = 3) {
    resultsEl.innerHTML = "";
    for (let i = 0; i < count; i++) {
        const skeleton = document.createElement("div");
        skeleton.className = "bg-secondary rounded mb-2";
        skeleton.style.height = "1.25rem";
        skeleton.style.opacity = "0.3";
        skeleton.classList.add("skeleton-loader");
        resultsEl.appendChild(skeleton);
    }
}

function resetActiveResult() {
    resultItems.forEach((el, i) => {
        if (i === activeIndex) {
            el.style.backgroundColor = "#b7b7b7";
            el.style.borderRadius = "5px";

            if (!suppressScroll) {
                el.scrollIntoView({
                    block: "center",
                    behavior: "smooth"
                });
            }
        } else {
            el.style.backgroundColor = "";
            el.style.borderRadius = "";
        }
    });
}

document.addEventListener("mousemove", () => {
    lastInputMethod = "mouse";
});

function clearNavigationState() {
    activeIndex = -1;
    resultItems = [];
}

document.addEventListener("keydown", function (e) {
    lastInputMethod = "keyboard";

    if (document.activeElement !== input) return;

    if (e.key === "ArrowDown") {
        e.preventDefault();
        if (activeIndex < resultItems.length - 1) {
            activeIndex++;
            resetActiveResult();
        }
    } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (activeIndex > 0) {
            activeIndex--;
            resetActiveResult();
        }
    } else if (e.key === "Enter") {
        e.preventDefault();
        if (activeIndex >= 0 && resultItems[activeIndex]) {
            const link = resultItems[activeIndex].querySelector("a");
            if (link) window.location.href = link.href;
        }
    }
});


function renderSkeleton(count = 3) {
    resultsEl.innerHTML = "";
    for (let i = 0; i < count; i++) {
      const skeleton = document.createElement("div");
      skeleton.className = "bg-secondary rounded mb-2";
      skeleton.style.height = "1.25rem";
      skeleton.style.opacity = "0.3";
      skeleton.classList.add("skeleton-loader");
      resultsEl.appendChild(skeleton);
    }
}

const debounce = (fn, delay) => {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
};
  
const handleInput = () => {
    const query = input.value.trim();
    if (query.length < 2) {
        resultsEl.innerHTML = "";
        clearNavigationState();
        return;
    }

    renderSkeleton()

    fetch(`/pwncollege_api/v1/search?q=${encodeURIComponent(query)}`)
        .then(res => res.json())
        .then(data => {
        resultsEl.innerHTML = "";
        clearNavigationState();

        if (!data.success) return;

        const { dojos, modules, challenges } = data.results;

        if ((!dojos || !dojos.length) && (!modules || !modules.length) && (!challenges || !challenges.length)) {
            const noResult = document.createElement("div");
            noResult.className = "text-light mt-2";
            noResult.textContent = "No results found";
            resultsEl.appendChild(noResult);
            return;
        }

        const renderItem = (text, url, match = null) => {
            const container = document.createElement("div");
            container.className = "d-block py-1";
        
            const link = document.createElement("a");
            link.href = url;
            link.className = "text-light";
            link.textContent = text;
            container.appendChild(link);
        
            if (match) {
                const snippet = document.createElement("div");
                snippet.className = "text-muted small";
                snippet.innerHTML = match;
                container.appendChild(snippet);
            }
        
            container.addEventListener("mouseenter", () => {
                if (lastInputMethod !== "mouse") return;
                suppressScroll = true;
                activeIndex = resultItems.indexOf(container);
                resetActiveResult();
                suppressScroll = false;
            });
        
            return container;
        };
        

        const renderSection = (label, items) => {
            const header = document.createElement("div");
            header.className = "text-secondary mt-3 mb-1 text-uppercase small font-weight-bold";
            header.textContent = label;
            resultsEl.appendChild(header);
            items.forEach(item => {
                resultsEl.appendChild(item);
                item.style.padding = "5px 10px";
                resultItems.push(item); 
            });
        };

        const dojoItems = data.results.dojos.map(d => renderItem(d.name, d.link, d.match));
        const moduleItems = data.results.modules.map(m =>
            renderItem(`${m.dojo.name} / ${m.name}`, m.link, m.match)
        );
        const challengeItems = data.results.challenges.map(c =>
            renderItem(`${c.dojo.name} / ${c.module.name} / ${c.name}`, c.link, c.match)
        );

        if (dojoItems.length) renderSection("Dojos", dojoItems);
        if (moduleItems.length) renderSection("Modules", moduleItems);
        if (challengeItems.length) renderSection("Challenges", challengeItems);
        });
};
  
input.addEventListener("input", debounce(handleInput, 200));