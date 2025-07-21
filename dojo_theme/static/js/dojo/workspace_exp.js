function alert(message) {
	document.getElementById("alert").innerHTML = message;
}

function reload_content() {
	var content = document.getElementById("challenge-content");
	content.src = content.src;
}

function set_content(option) {
	// TODO: more advanced control via the option's value.
	var content = document.getElementById("challenge-content");
	content.src = option.value;
}

function start_challenge(privileged) {
	alert("Loading...");

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
			alert(result.error);
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
				alert("Error: " + result.error);
			}

			alert("Challenge started");

			reload_content();
		})
	});
}

function challenge_start_callback(event) {
	event.preventDefault();

	if (event.target.id == "start") {
		start_challenge(false);
	}
	else if (event.target.id == "start-priv") {
		start_challenge(true);
	}
	else if (event.target.id == "restart") {
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
		alert("WTF?");
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

$(() => {
	var option = document.getElementById("active");
	option.selected = true;
	set_content(option);

	kill_footer();
	if (document.getElementById("hide-navbar") != null) {
		kill_navbar();
	}

	$("#workspace-select").change(content_select_callback);
	document.getElementById("start").onclick = challenge_start_callback;
	if (document.getElementById("start-priv") != null) {
		document.getElementById("start-priv").onclick = challenge_start_callback;
	}
	document.getElementById("restart").onclick = challenge_start_callback;
});