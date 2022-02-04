$(() => {
    $('a[data-toggle="pill"]').on("show.bs.tab", function (event) {
        console.log(event.currentTarget);
        const target = $($(event.currentTarget).attr("href"));
        target.find("embed").each(function (i, embed) {
            if ($(embed).prop("src"))
                return;
            $(embed).prop("src", function () {
                return $(this).data("src");
            });
        });
    });
});
