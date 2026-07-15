const scoreboardState = {
    generation: 0,
    view: location.hash === "#crews" || location.hash === "#crews-unique" ? "crews" : "hackers",
    crewMode: location.hash === "#crews-unique" ? "unique" : "cumulative",
    duration: 30,
};

function crewColors(key) {
    let hash = 5381;
    for (let i = 0; i < key.length; i++) hash = ((hash << 5) + hash + key.charCodeAt(i)) >>> 0;
    const hue = hash % 360;
    return {
        text: `hsl(${hue}, 60%, 65%)`,
        border: `hsla(${hue}, 60%, 65%, 0.55)`,
        background: `hsla(${hue}, 60%, 65%, 0.12)`,
    };
}

function fetchScoreboardPage(duration, page, crews) {
    const dojo = init.dojo;
    const module = init.module || "_";
    const endpoint = crews
        ? `/pwncollege_api/v1/scoreboard/${dojo}/${module}/crews/${duration}/${page}?mode=${scoreboardState.crewMode}`
        : `/pwncollege_api/v1/scoreboard/${dojo}/${module}/${duration}/${page}`;
    return CTFd.fetch(endpoint, {
        method: "GET",
        credentials: "same-origin",
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json"
        },
    }).then(response => {
        if (!response.ok) throw new Error(`scoreboard page ${page} returned ${response.status}`);
        return response.json();
    });
}

function buildCrewTagChip(tag, key) {
    const colors = crewColors(key);
    const chip = $(`
        <span class="crew-tag"><span class="crew-tag-bracket">[</span><bdi class="crew-tag-text"></bdi><span class="crew-tag-bracket">]</span></span>
    `);
    chip.find(".crew-tag-text").text(tag);
    chip.css({ "color": colors.text, "border-color": colors.border, "background-color": colors.background });
    return chip;
}

function buildHackerRow(user, me, crew) {
    const row = $(`
    <tr>
      <td scope="row" class="col-md-1"><b class="scoreboard-rank"></b></td>
      <td class="col-md-1 p-0">
        <img class="scoreboard-symbol">
      </td>
      <td class="col-md-4">
        <a class="scoreboard-name brand-mono"></a>
      </td>
      <td class="scoreboard-completions col-md-4">
      </td>
      <td class="col-md-1">
        <img class="scoreboard-belt">
      </td>
      <td class="col-md-1"><b class="scoreboard-score"></b></td>
    </tr>
    `);
    row.find(".scoreboard-rank").text(`#${user.rank}`);
    row.find(".scoreboard-symbol").attr("src", user.symbol);
    row.find(".scoreboard-belt").attr("src", user.belt);
    row.find(".scoreboard-score").text(user.solves);
    const name = row.find(".scoreboard-name").attr("href", user.url).attr("title", user.name);
    if (crew) {
        row.addClass("crew-member-row").css("border-left-color", crewColors(crew.key).text);
        name.text(((user.crew && user.crew.base_name) || user.name).slice(0, 50));
    } else if (user.crew) {
        name.text(user.crew.base_name.slice(0, 50));
        name.append(buildCrewTagChip(user.crew.tag, user.crew.key));
    } else {
        name.text(user.name.slice(0, 50));
    }
    const completions = row.find(".scoreboard-completions");
    (user.badges || []).forEach(badge => {
        const span = $(`<span><a class="scoreboard-badge"></a><sub class="scoreboard-badge-count"></sub></span>`);
        span.attr("title", badge.text);
        span.find(".scoreboard-badge").attr("href", badge.url || "#").text(badge.emoji);
        if (badge.count > 1) span.find(".scoreboard-badge-count").text(`x${badge.count}`);
        else span.find(".scoreboard-badge-count").remove();
        if (badge.stale) span.css({ "opacity": 0.4, "filter": "grayscale(100%)" });
        completions.append(span, " ");
    });
    if (me && user.user_id === me.user_id) row.addClass("scoreboard-row-me");
    return row;
}

function buildCrewRow(crew, myCrewKey) {
    const colors = crewColors(crew.key);
    const row = $(`
    <tr class="crew-row" role="button" tabindex="0" aria-expanded="false">
      <td scope="row" class="col-md-1"><i class="fas fa-caret-right crew-caret" aria-hidden="true"></i> <b class="crew-rank"></b></td>
      <td class="col-md-1 p-0">
        <span class="crew-crest brand-mono"></span>
      </td>
      <td class="col-md-4 crew-name-cell">
      </td>
      <td class="col-md-4 crew-facepile">
      </td>
      <td class="col-md-1">
        <img class="scoreboard-belt">
      </td>
      <td class="col-md-1"><b class="crew-score"></b></td>
    </tr>
    `);
    row.find(".crew-rank").text(`#${crew.rank}`);
    if (crew.rank <= 3) row.addClass(`crew-rank-${crew.rank}`);
    const crest = row.find(".crew-crest");
    crest.text(Array.from(crew.tag)[0].toUpperCase());
    crest.css({ "color": colors.text, "border-color": colors.border, "background-color": colors.background });
    const nameCell = row.find(".crew-name-cell");
    nameCell.append(buildCrewTagChip(crew.tag, crew.key));
    const count = $(`<span class="crew-member-count"></span>`);
    count.text(`${crew.members.length} member${crew.members.length === 1 ? "" : "s"}`);
    nameCell.append(count);
    const facepile = row.find(".crew-facepile");
    crew.members.slice(0, 5).forEach(member => {
        facepile.append($(`<img class="crew-face">`).attr("src", member.symbol));
    });
    if (crew.members.length > 5) {
        facepile.append($(`<span class="crew-face-more brand-mono"></span>`).text(`+${crew.members.length - 5}`));
    }
    const names = crew.members.slice(0, 5).map(member => member.name).join(", ");
    facepile.attr("title", crew.members.length > 5 ? `${names}, …` : names);
    const top = crew.members[0];
    row.find(".scoreboard-belt").attr("src", top.belt).attr("title", `Top member: ${top.name}`);
    const unique = crew.unique === null || crew.unique === undefined ? "—" : crew.unique.toLocaleString();
    const scoreCell = row.find(".crew-score");
    if (scoreboardState.crewMode === "unique") scoreCell.text(unique);
    else scoreCell.text(crew.score.toLocaleString());
    scoreCell.attr("title", `Cumulative: ${crew.score.toLocaleString()} · Unique challenges: ${unique}`);
    if (myCrewKey && crew.key === myCrewKey) row.addClass("scoreboard-row-me");

    let memberRows = null;
    let expanded = false;
    const attachMembers = () => {
        const me = init.userId ? { user_id: Number(init.userId) } : null;
        const rows = crew.members.map(user => buildHackerRow(user, me, crew));
        const head = rows.slice(0, 10);
        const rest = rows.slice(10);
        memberRows = head.slice();
        if (rest.length) {
            const moreRow = $(`<tr class="crew-more-row"><td colspan="6"><a role="button" tabindex="0"></a></td></tr>`);
            moreRow.find("a").text(`▾ show ${rest.length} more member${rest.length === 1 ? "" : "s"}`);
            const showRest = () => {
                rest.forEach(memberRow => memberRow.insertBefore(moreRow));
                moreRow.remove();
                memberRows = head.concat(rest);
            };
            moreRow.on("click", showRest);
            moreRow.find("a").on("keydown", event => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    showRest();
                }
            });
            memberRows.push(moreRow);
        }
        let anchor = row;
        memberRows.forEach(memberRow => {
            anchor.after(memberRow);
            anchor = memberRow;
        });
    };
    const toggle = () => {
        expanded = !expanded;
        row.attr("aria-expanded", expanded ? "true" : "false");
        row.toggleClass("crew-row-open", expanded);
        if (expanded && !memberRows) attachMembers();
        else if (memberRows) memberRows.forEach(memberRow => expanded ? memberRow.show() : memberRow.hide());
    };
    row.on("click", toggle);
    row.on("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggle();
        }
    });
    return row;
}

function setScoreboardControls(view, duration) {
    $("#scoreboard-control-week, #scoreboard-control-month, #scoreboard-control-all").removeClass("scoreboard-page-selected");
    const labels = { 7: "7-Day", 30: "30-Day", 0: "All-Time" };
    const controls = { 7: "#scoreboard-control-week", 30: "#scoreboard-control-month", 0: "#scoreboard-control-all" };
    if (controls[duration]) $(controls[duration]).addClass("scoreboard-page-selected");
    const crews = view === "crews";
    const unique = scoreboardState.crewMode === "unique";
    $("#scoreboard-heading").text(`${labels[duration] || ""}${crews ? " Crew" : ""} Scoreboard:`);
    $("#scoreboard-th-name").text(crews ? "Crew" : "Hacker");
    $("#scoreboard-th-badges").text(crews ? "Members" : "Badges");
    $("#scoreboard-th-score").text(crews && unique ? "Unique" : "Score");
    $("#scoreboard-view-hackers").toggleClass("scoreboard-view-selected", !crews).attr("aria-selected", String(!crews));
    $("#scoreboard-view-crews").toggleClass("scoreboard-view-selected", crews).attr("aria-selected", String(crews));
    $("#scoreboard-crew-mode-toggle").prop("hidden", !crews);
    $("#scoreboard-crew-mode-cumulative").toggleClass("scoreboard-view-selected", !unique).attr("aria-selected", String(!unique));
    $("#scoreboard-crew-mode-unique").toggleClass("scoreboard-view-selected", unique).attr("aria-selected", String(unique));
    $(".scoreboard").toggleClass("scoreboard-crew-mode", crews);
}

function renderPagination(duration, page, pages) {
    const scoreboardPages = $("#scoreboard-pages");
    scoreboardPages.empty();
    if (pages.length > 1) {
        pages.forEach(i => {
            const pageButton = $(`<li class="scoreboard-page"><a></a></li>`);
            pageButton.find("a").attr("href", `javascript:loadScoreboard(${Number(duration)}, ${Number(i)})`).text(i);
            pageButton.addClass(i == page ? "scoreboard-page-selected" : "scoreboard-page-unselected");
            scoreboardPages.append(pageButton);
        });
    }
}

function renderNoteRow(text) {
    const row = $(`<tr class="crew-note-row"><td colspan="6" class="crew-note"></td></tr>`);
    row.find(".crew-note").text(text);
    $("#scoreboard").append(row);
    return row;
}

function renderLoadingRow() {
    $("#scoreboard").empty().append($(`<tr class="scoreboard-loading"><td colspan="6">Loading...</td></tr>`));
    $("#scoreboard-pages").empty();
}

function renderErrorRow(duration, page, message) {
    $("#scoreboard").empty();
    const warning = renderNoteRow(`${message} `);
    warning.find(".crew-note").addClass("crew-note-warn");
    const retry = $(`<a role="button" tabindex="0" href="javascript:void(0)">Retry</a>`);
    retry.on("click", () => loadScoreboard(duration, page));
    warning.find(".crew-note").append(retry);
}

function renderCrewEmptyState() {
    const row = $(`
      <tr class="crew-empty"><td colspan="6">
        <div><span class="crew-tag crew-tag-ghost"><span class="crew-tag-bracket">[</span><bdi class="crew-tag-text">YOUR-CREW</bdi><span class="crew-tag-bracket">]</span></span></div>
        <div class="crew-empty-title">No crews yet.</div>
        <div class="crew-empty-hint">Start one: add a tag in brackets to your display name in <a>Settings</a> — e.g. <b>Zardus [Shellphish]</b> — and your crew appears here.</div>
      </td></tr>
    `);
    row.find("a").attr("href", `${init.urlRoot}/settings`);
    $("#scoreboard").append(row);
}

function renderCrewView(duration, page, gen) {
    renderLoadingRow();
    fetchScoreboardPage(duration, page, true).then(result => {
        if (gen !== scoreboardState.generation) return;
        const scoreboard = $("#scoreboard");
        scoreboard.empty();
        const crews = result.standings.slice();
        const myCrew = result.me_crew || null;
        const myCrewKey = myCrew ? myCrew.key : null;

        if (!crews.length) {
            if (result.board_empty) renderNoteRow("No solves yet — no crews to show.");
            else renderCrewEmptyState();
            renderPagination(duration, 1, []);
            return;
        }

        if (myCrew && !crews.some(crew => crew.key === myCrew.key)) {
            if (myCrew.rank < crews[0].rank) crews.splice(0, 0, myCrew);
            else crews.push(myCrew);
        }
        crews.forEach((crew, i) => {
            const row = buildCrewRow(crew, myCrewKey);
            if (i % 2 === 0) row.addClass("crew-row-stripe");
            scoreboard.append(row);
        });
        renderPagination(duration, page, result.pages);
    }).catch(() => {
        if (gen !== scoreboardState.generation) return;
        renderErrorRow(duration, page, "Failed to load the crew scoreboard.");
    });
}

function renderHackerView(duration, page, gen) {
    renderLoadingRow();
    fetchScoreboardPage(duration, page, false).then(result => {
        if (gen !== scoreboardState.generation) return;
        const scoreboard = $("#scoreboard");
        scoreboard.empty();
        const standings = result.standings.slice();
        if (result.me && standings.length) {
            if (result.me.rank < standings[0].rank)
                standings.splice(0, 0, result.me);
            else if (result.me.rank > standings[standings.length - 1].rank)
                standings.splice(standings.length, 0, result.me);
        }
        if (!standings.length) {
            renderNoteRow("No solves yet.");
        }
        standings.forEach(user => {
            scoreboard.append(buildHackerRow(user, result.me, null));
        });
        renderPagination(duration, page, result.pages);
    }).catch(() => {
        if (gen !== scoreboardState.generation) return;
        renderErrorRow(duration, page, "Failed to load the scoreboard.");
    });
}

function loadScoreboard(duration, page) {
    duration = Number(duration);
    page = Number(page);
    scoreboardState.duration = duration;
    const gen = ++scoreboardState.generation;
    setScoreboardControls(scoreboardState.view, duration);
    if (scoreboardState.view === "crews") renderCrewView(duration, page, gen);
    else renderHackerView(duration, page, gen);
}

function scoreboardHash() {
    if (scoreboardState.view !== "crews") return location.pathname + location.search;
    return scoreboardState.crewMode === "unique" ? "#crews-unique" : "#crews";
}

function setScoreboardView(view) {
    if (scoreboardState.view === view) return;
    scoreboardState.view = view;
    if (history.replaceState) history.replaceState(null, "", scoreboardHash());
    loadScoreboard(scoreboardState.duration, 1);
}

function setCrewMode(mode) {
    if (scoreboardState.crewMode === mode) return;
    scoreboardState.crewMode = mode;
    if (history.replaceState) history.replaceState(null, "", scoreboardHash());
    loadScoreboard(scoreboardState.duration, 1);
}
