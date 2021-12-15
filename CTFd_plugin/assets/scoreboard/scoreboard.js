function loadScoreboard(name, page) {
    const scoreboard = $(`#scoreboard-${name}`);

    var endpoint = `/pwncollege_api/v1/scoreboard/${name}`;
    if (page != null)
        endpoint += `/${page - 1}`;

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
              <td>
                <img src="${user.belt}" class="scoreboard-belt">
              </td>
              <td><b>${user.score}</b></td>
            </tr>
            `);
            row.find(".scoreboard-name").text(user.name.slice(0, 50));
            if (result.me && user.place == result.me.place)
                row.addClass("scoreboard-row-me");
            scoreboard.append(row);
        });

        if (page != null) {
            const scoreboardPages = $(`#scoreboard-${name}-pages`);
            scoreboardPages.empty();
            const minPage = Math.max(1, page - 5);
            const maxPage = Math.min(page + 5, result.num_pages);
            for (let i = minPage; i <= maxPage; i++) {
                const pageButton = $(`
                <li class="scoreboard-page"><a href="javascript:loadScoreboard('${name}', ${i})">${i}</a></li>
                `);
                pageButton.addClass(i == page ? "scoreboard-page-selected" : "scoreboard-page-unselected");
                scoreboardPages.append(pageButton);
            }
        }
    });
}


$(function() {
    loadScoreboard("weekly");
    loadScoreboard("overall", 1);
});
