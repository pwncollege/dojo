function alert(message) {
	document.getElementById("alert").innerHTML = message;
}

function reload_content() {
	set_content(document.getElementById("workspace-select"));
}

function process_content_operation_recursive(operations, content) {
	if (operations.length == 0) {
		return;
	}

	var operation = operations[0];

	if (operation.match(/GET:.*/) != null) {
		fetch(operation.substring(4), {
			method: "GET",
			credentials: 'same-origin',
		}).then(() => {
			process_content_operation_recursive(operations.slice(1, operations.length), content);
		});
	}
	else if (operation.match(/GET&RENDER:.*/)) {
		var op = operation.substring(11);
		var delin = op.indexOf(":");
		url = op.substring(delin + 1);
		param = op.substring(0, delin);

		fetch(url, {
			method: "GET",
			credentials: "same-origin",
		}).then(function (response) {
			return response.json();
		}).then(function (result) {
			content.src = result[param];
			process_content_operation_recursive(operations.slice(1, operations.length), content);
		})
	}
	else if (operation.match(/RENDER:.*/)) {
		content.src = operation.substring(7);
	}
	else {
		console.log("Error processing content operation: " + operation);
	}

	process_content_operation_recursive(operations.slice(1, operations.length), content);
}

function set_content(option) {
	console.log(option);
	var operations = option.value.split(";");
	var content = document.getElementById("challenge-content");

	process_content_operation_recursive(operations, content);
}

function start_challenge(privileged) {
	CTFd.fetch("/pwncollege_api/v1/docker", {
		method: "GET",
		credentials: 'same-origin'
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
		if (result.success == false) {
			return;
		}

		var params = {
			"dojo": result.dojo,
			"module": result.module,
			"challenge": result.challenge,
			"practice": privileged,
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
			return response.json;
		}).then(function (result) {
			if (result.success == false) {
				return;
			}

			reload_content();

			$(".btn-challenge-start")
			.removeClass("disabled")
			.removeClass("btn-disabled")
			.prop("disabled", false);
		})
	});
}

function challenge_start_callback(event) {
	event.preventDefault();

	$(".btn-challenge-start")
	.addClass("disabled")
	.addClass("btn-disabled")
	.prop("disabled", true);

	if (document.getElementById("start").contains(event.target)) {
		start_challenge(false);
	}
	else if (document.getElementById("start-priv").contains(event.target)) {
		start_challenge(true);
	}
	else if (document.getElementById("restart").contains(event.target)) {
		CTFd.fetch("/pwncollege_api/v1/docker", {
			method: "GET",
			credentials: 'same-origin'
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
			start_challenge(result.practice);
		});
	}
	else {
		console.log("Unexpected element attempted to start a challenge:")
		console.log(event.target);

		$(".btn-challenge-start")
		.removeClass("disabled")
		.removeClass("btn-disabled")
		.prop("disabled", false);
	}
}

function content_select_callback(event) {
	event.preventDefault();

	set_content(event.target);
}

function kill_navbar() {
	var navbar = document.getElementsByClassName("navbar-expand-md")[0];
	var navbar_pull = document.getElementsByClassName("navbar-pulldown")[0];
	var navbar_search = document.getElementById("searchModal");

	navbar.remove();
	navbar_pull.remove();
	navbar_search.remove();
}

function kill_footer() {
	var footer = document.getElementsByClassName("footer")[0];

	footer.remove();
}

function submit_flag(flag) {
	console.log("Submitting flag " + flag);

	flag_input = document.getElementById("flag-input");
	flag_input.value = "";
	flag_input.placeholder = "Submitting...";

	var body = {
		'challenge_id': parseInt(document.getElementById("current-challenge-id").value),
		'submission': flag,
	};
	var params = {};

	CTFd.api.post_challenge_attempt(params, body)
	.then(function (response) {
		if (response.data.status == "incorrect") {
			flag_input.placeholder = "Incorrect!";
			flag_input.classList.add("submit-incorrect");
		}
		else if (response.data.status == "correct") {
			flag_input.placeholder = "Correct!";
			flag_input.classList.add("submit-correct");
		}
		else if (response.data.status == "already_solved") {
			flag_input.placeholder = "Already Solved.";
			flag_input.classList.add("submit-correct");
		}
		else {
			flag_input.placeholder = "WTF???";
			flag_input.classList.add("submit-warn");
		}
	});
}

function flag_input_callback(event) {
	event.preventDefault();
	event.target.classList.remove("submit-correct");
	event.target.classList.remove("submit-incorrect");
	event.target.classList.remove("submit-warn");
	event.target.placeholder = "Flag";
	const flag_regex = /pwn.college{.*}/;

	if (event.target.value.match(flag_regex) == null) {
		return;
	}

	submit_flag(event.target.value);
}

function trim_navbar() {
	document.getElementsByClassName("close-link")[0].parentElement.remove();
	document.getElementsByClassName("navbar-pulldown")[0].remove();
}

function hide_navbar() {
	$(".navbar").addClass("navbar-hidden");
	$("main").addClass("main-navbar-hidden");
}

function show_navbar() {
	$(".navbar").removeClass("navbar-hidden");
	$("main").removeClass("main-navbar-hidden");
}

function toggle_navbar() {
	if (document.getElementsByClassName("navbar")[0].classList.contains("navbar-hidden")) {
		show_navbar();
		document.getElementById("fullscreen").innerHTML = "<i class=\"fas fa-expand fa-2x\"></i>";
	}
	else {
		hide_navbar();
		document.getElementById("fullscreen").innerHTML = "<i class=\"fas fa-compress fa-2x\"></i>";
	}
}

function do_fullscreen() {
	toggle_navbar();
}

function fullscreen_callback(event) {
	event.preventDefault();
	// If the window is not an iframe, this will refer to its own do_fullscreen function.
	// Otherwise it will call the do_fullscreen function of the window which we are iframed into.
	window.parent.do_fullscreen();
}

$(() => {
	var option = document.getElementById("active");
	option.selected = true;
	set_content(option);

	kill_footer();
	if (document.getElementById("hide-navbar") != null) {
		kill_navbar();
	}
	else {
		trim_navbar();
	}

	$("#workspace-select").change(content_select_callback);
	$(".btn-challenge-start").click(challenge_start_callback);
	
	document.getElementById("flag-input").oninput = flag_input_callback;

	if (document.getElementById("fullscreen") != null) {
		document.getElementById("fullscreen").onclick = fullscreen_callback;
	}
});