function selector(event) {
	return $(event.target).closest(".selector-body");
}

function selectorOpen(event) {
	var root = selector(event);
	root.find(".selector-options").toggleClass("selector-collapsed");
	root.find(".selector-active").toggleClass("selector-hat");
}

function selectorChoose(event) {
	var root = selector(event);
	root.find(".selector-options").addClass("selector-collapsed");
	root.find(".selector-active").removeClass("selector-hat");

	select(root, $(event.target).prop("value"), $(event.target).html())

	event.target.dispatchEvent(new Event("selected"));
}

function select(root, value, display) {
	root.find(".selector-current")
		.prop("value", value)
		.html(display);
}

$(() => {
	$(".selector-open").click(selectorOpen);
	$(".selector-choose").click(selectorChoose).on("selected", (event) => {
		console.log(event);
	});
});