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
});
