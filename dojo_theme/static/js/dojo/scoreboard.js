function loadScoreboard(duration, page) {
    const dojo = init.dojo;
    const module = init.module || "_";
    const scoreboard = $("#scoreboard");

    const endpoint = `/pwncollege_api/v1/scoreboard/${dojo}/${module}/${duration}/${page}`;
    scoreboard.empty();
    message = "Loading."
    scoreboard.html(`<td colspan=6>${message}</td>`);
    setTimeout(function loadmsg() {
        if (scoreboard.html().includes(message)) {
            message += "."
            scoreboard.html(`<td colspan=6>${message}</td>`);
            setTimeout(loadmsg, 1000);
        }
    }, 500);
    $("#scoreboard-control-week").removeClass("scoreboard-page-selected");
    $("#scoreboard-control-month").removeClass("scoreboard-page-selected");
    $("#scoreboard-control-all").removeClass("scoreboard-page-selected");
    if (duration == 7) $("#scoreboard-control-week").addClass("scoreboard-page-selected");
    if (duration == 30) $("#scoreboard-control-month").addClass("scoreboard-page-selected");
    if (duration == 0) $("#scoreboard-control-all").addClass("scoreboard-page-selected");

    CTFd.fetch(endpoint, {
        method: "GET",
        credentials: "same-origin",
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json"
        },
    }).then(response => {
        return response.json()
    }).then(result => {
        scoreboard.empty();

        const standings = result.standings;
        if (result.me) {
            if (result.me.rank < standings[0].rank)
                standings.splice(0, 0, result.me)
            else if (result.me.rank > standings[standings.length - 1].rank)
                standings.splice(standings.length, 0, result.me)
        }
        standings.forEach(user => {
            const row = $(`
            <tr>
              <td scope="row" class="col-md-1"><b>#${user.rank}</b></td>
              <td class="col-md-1 p-0">
                <img src="${user.symbol}" class="scoreboard-symbol">
              </td>
              <td class="col-md-4">
                <a href="${user.url}" class="scoreboard-name text-decoration-none">
                </a>
              </td>
              <td class="scoreboard-completions col-md-4">
              </td>
              <td class="col-md-1">
                <img src="${user.belt}" class="scoreboard-belt">
              </td>
              <td class="col-md-1"><b>${user.solves}</b></td>
            </tr>
            `);
            row.find(".scoreboard-name").text(user.name.slice(0, 50));

            user.badges.forEach(badge => {
                if (!badge.url) badge.url = "#";
                var count = badge.count <= 1 ? "" : `<sub>x${badge.count}</sub>`
                row.find(".scoreboard-completions").append($(`
                    <span title="${badge.text}">
                    <a href="${badge.url}">${badge.emoji}</a>${count}
                    </span><span> </span>
                `));
            })

            if (result.me && user.user_id == result.me.user_id)
                row.addClass("scoreboard-row-me");
            scoreboard.append(row);
        });

        const scoreboardPages = $("#scoreboard-pages");
        scoreboardPages.empty();//A
        if (result.pages.length > 1) {
            result.pages.forEach(i => {
                const pageButton = $(`
                <li class="scoreboard-page"><a href="javascript:loadScoreboard('${duration}', ${i})">${i}</a></li>
                `);
                pageButton.addClass(i == page ? "scoreboard-page-selected" : "scoreboard-page-unselected");
                scoreboardPages.append(pageButton);
            });
        }
    });
}
