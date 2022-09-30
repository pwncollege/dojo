function loadScoreboard(duration, page) {
    const dojo = init.dojo_id;
    const module = init.module_id;
    const scoreboard = $("#scoreboard");

    if (module && module != "None") {
        var endpoint = `/pwncollege_api/v1/scoreboard/${dojo}/${module}/${duration}/${page - 1}`;
    }
    else {
        var endpoint = `/pwncollege_api/v1/scoreboard/${dojo}/${duration}/${page - 1}`;
    }

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
        const standings = result.page_standings;
        if (result.me) {
            if (result.me.place < standings[0].place)
                standings.splice(0, 0, result.me)
            else if (result.me.place > standings[standings.length - 1].place)
                standings.splice(standings.length, 0, result.me)
        }
        standings.forEach(user => {
            const row = $(`
            <tr>
              <th scope="row">#${user.place}</th>
              <td class="p-0">
                <img src="${user.symbol}" class="scoreboard-symbol">
              </td>
              <td>
                <a href="${user.url}" class="scoreboard-name text-decoration-none">
                </a>
              </td>
              <td class="scoreboard-completions">
              </td>
              <td>
                <img src="${user.belt}" class="scoreboard-belt">
              </td>
              <td><b>${user.score}</b></td>
            </tr>
            `);
            row.find(".scoreboard-name").text(user.name.slice(0, 50));
            user.completions.forEach(dojo => {
                dojolink = $(`<a href="/${dojo}/">${dojo}</a><span> </span>`)
                row.find(".scoreboard-completions").append(dojolink)
            });

            if (result.me && user.place == result.me.place)
                row.addClass("scoreboard-row-me");
            scoreboard.append(row);
        });

        const scoreboardPages = $("#scoreboard-pages");
        scoreboardPages.empty();
        const minPage = Math.max(1, page - 5);
        const maxPage = Math.min(page + 5, result.num_pages);
        for (let i = minPage; i <= maxPage; i++) {
            const pageButton = $(`
            <li class="scoreboard-page"><a href="javascript:loadScoreboard('${duration}', ${i})">${i}</a></li>
            `);
            pageButton.addClass(i == page ? "scoreboard-page-selected" : "scoreboard-page-unselected");
            scoreboardPages.append(pageButton);
        }
    });
}
