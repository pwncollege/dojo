function loadScoreboard(duration, page) {
    const dojo_id = init.dojo_id;
    const module_id = init.module_id || "_";
    const scoreboard = $("#scoreboard");

    const endpoint = `/pwncollege_api/v1/scoreboard/${dojo_id}/${module_id}/${duration}/${page}`;

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
              <th scope="row">#${user.rank}</th>
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
        scoreboardPages.empty();
        result.pages.forEach(i => {
            const pageButton = $(`
            <li class="scoreboard-page"><a href="javascript:loadScoreboard('${duration}', ${i})">${i}</a></li>
            `);
            pageButton.addClass(i == page ? "scoreboard-page-selected" : "scoreboard-page-unselected");
            scoreboardPages.append(pageButton);
        });
    });
}
