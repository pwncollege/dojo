const CREW_MAX_PAGES = 50;
const CREW_FETCH_CONCURRENCY = 4;
const CREW_CACHE_TTL_MS = 5 * 60 * 1000;
const CREW_TAG_RE = /^(.*?)\s*\[([^\[\]]{1,24})\]\s*$/;
const CREW_STRIP_RE = /[\u0000-\u001f\u007f-\u009f\u00ad\u034f\u17b4\u17b5\u180b-\u180e\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u{e0000}-\u{e007f}]/gu;
const CREW_KEY_STRIP_RE = /[\ufe00-\ufe0f]/g;

const scoreboardState = {
    generation: 0,
    view: location.hash === "#crews" ? "crews" : "hackers",
    duration: 30,
    crewCache: new Map(),
};

function parseCrewTag(name) {
    const match = CREW_TAG_RE.exec(name);
    if (!match) return null;
    const tag = match[2].replace(CREW_STRIP_RE, "").replace(/\s+/g, " ").trim();
    if (tag.length < 1 || tag.length > 20) return null;
    return { tag: tag, key: tag.replace(CREW_KEY_STRIP_RE, "").normalize("NFKC").toLowerCase(), baseName: match[1].trim() };
}
window.parseCrewTag = parseCrewTag;

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

function fetchScoreboardPage(duration, page) {
    const dojo = init.dojo;
    const module = init.module || "_";
    const endpoint = `/pwncollege_api/v1/scoreboard/${dojo}/${module}/${duration}/${page}`;
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

async function runCrewFetch(entry, duration) {
    if (!entry.pagesByNumber.has(1)) {
        const first = await fetchScoreboardPage(duration, 1);
        entry.me = first.me || null;
        entry.pagesByNumber.set(1, first.standings);
        entry.totalPages = first.pages && first.pages.length ? Math.max.apply(null, first.pages) : 1;
        entry.capped = entry.totalPages > CREW_MAX_PAGES;
    }
    const fetchCount = Math.min(entry.totalPages, CREW_MAX_PAGES);
    const missing = [];
    for (let page = 2; page <= fetchCount; page++) {
        if (!entry.pagesByNumber.has(page)) missing.push(page);
    }
    entry.failedPages = [];
    let done = fetchCount - missing.length;
    const report = () => { if (entry.onProgress) entry.onProgress(done, fetchCount); };
    report();
    let next = 0;
    const worker = async () => {
        while (next < missing.length) {
            const page = missing[next++];
            try {
                let result;
                try {
                    result = await fetchScoreboardPage(duration, page);
                } catch (error) {
                    result = await fetchScoreboardPage(duration, page);
                }
                entry.pagesByNumber.set(page, result.standings);
            } catch (error) {
                entry.failedPages.push(page);
            }
            done++;
            report();
        }
    };
    await Promise.all(Array.from({ length: CREW_FETCH_CONCURRENCY }, worker));
    return entry;
}

function fetchAllStandings(duration, gen) {
    const key = `${init.dojo}|${init.module || "_"}|${duration}`;
    let entry = scoreboardState.crewCache.get(key);
    if (!entry || Date.now() - entry.fetchedAt >= CREW_CACHE_TTL_MS) {
        entry = {
            fetchedAt: Date.now(),
            pagesByNumber: new Map(),
            totalPages: 1,
            capped: false,
            failedPages: [],
            me: null,
            promise: null,
            running: false,
            onProgress: null,
        };
        scoreboardState.crewCache.set(key, entry);
    }
    entry.onProgress = (done, total) => {
        if (gen === scoreboardState.generation) updateCrewProgress(done, total);
    };
    if (!entry.promise || (!entry.running && entry.failedPages.length)) {
        entry.running = true;
        entry.promise = runCrewFetch(entry, duration)
            .catch(error => {
                scoreboardState.crewCache.delete(key);
                throw error;
            })
            .finally(() => { entry.running = false; });
    }
    return entry.promise;
}

function dedupStandings(entry) {
    const byUser = new Map();
    const pages = Array.from(entry.pagesByNumber.keys()).sort((a, b) => a - b);
    pages.forEach(page => {
        entry.pagesByNumber.get(page).forEach(user => {
            if (!byUser.has(user.user_id)) byUser.set(user.user_id, user);
        });
    });
    return Array.from(byUser.values()).sort((a, b) => a.rank - b.rank);
}

function aggregateCrews(standings) {
    const crews = new Map();
    standings.forEach(user => {
        const parsed = parseCrewTag(user.name);
        if (!parsed) return;
        if (!crews.has(parsed.key)) {
            crews.set(parsed.key, { key: parsed.key, tag: parsed.tag, score: 0, bestRank: user.rank, members: [] });
        }
        const crew = crews.get(parsed.key);
        crew.score += user.solves;
        crew.members.push(user);
    });
    const ranked = Array.from(crews.values()).sort((a, b) =>
        b.score - a.score
        || a.members.length - b.members.length
        || a.bestRank - b.bestRank
        || a.key.localeCompare(b.key)
    );
    ranked.forEach((crew, i) => { crew.rank = i + 1; });
    return ranked;
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
    const parsed = parseCrewTag(user.name);
    if (crew) {
        row.addClass("crew-member-row").css("border-left-color", crewColors(crew.key).text);
        name.text(((parsed && parsed.baseName) || user.name).slice(0, 50));
    } else if (parsed) {
        name.text(parsed.baseName.slice(0, 50));
        name.append(buildCrewTagChip(parsed.tag, parsed.key));
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

function buildCrewRow(crew, me, myCrewKey) {
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
    row.find(".crew-score").text(crew.score.toLocaleString()).attr("title", `Sum of ${crew.members.length} members' scores`);
    if (myCrewKey && crew.key === myCrewKey) row.addClass("scoreboard-row-me");

    let memberRows = null;
    let expanded = false;
    const attachMembers = () => {
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
    $("#scoreboard-heading").text(`${labels[duration] || ""}${crews ? " Crew" : ""} Scoreboard:`);
    $("#scoreboard-th-name").text(crews ? "Crew" : "Hacker");
    $("#scoreboard-th-badges").text(crews ? "Members" : "Badges");
    $("#scoreboard-view-hackers").toggleClass("scoreboard-view-selected", !crews).attr("aria-selected", String(!crews));
    $("#scoreboard-view-crews").toggleClass("scoreboard-view-selected", crews).attr("aria-selected", String(crews));
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

function renderCrewLoading() {
    $("#scoreboard").empty().append($(`
      <tr class="crew-loading"><td colspan="6">
        <div class="crew-loading-text brand-mono" aria-live="polite">Assembling crews…</div>
        <div class="crew-progress-track"><div class="crew-progress-fill"></div></div>
      </td></tr>
    `));
    $("#scoreboard-pages").empty();
}

function updateCrewProgress(done, total) {
    if (total < 1) total = 1;
    $("#scoreboard .crew-loading-text").text(`Assembling crews… page ${done} / ${total}`);
    $("#scoreboard .crew-progress-fill").css("width", `${Math.round(done / total * 100)}%`);
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

function renderCrewNotes(entry, duration, page) {
    if (entry.capped) {
        renderNoteRow(`Crew standings computed from the top ${(CREW_MAX_PAGES * 20).toLocaleString()} hackers on this board.`);
    }
    if (entry.failedPages.length) {
        const warning = renderNoteRow("Some pages failed to load — standings may be incomplete. ");
        warning.find(".crew-note").addClass("crew-note-warn");
        const retry = $(`<a role="button" tabindex="0" href="javascript:void(0)">Retry</a>`);
        retry.on("click", () => loadScoreboard(duration, page));
        warning.find(".crew-note").append(retry);
    }
}

function renderCrewBoard(entry, duration, page) {
    const scoreboard = $("#scoreboard");
    scoreboard.empty();
    const standings = dedupStandings(entry);
    const crews = aggregateCrews(standings);
    const me = entry.me;
    const myParsed = me ? parseCrewTag(me.name) : null;
    const myCrewKey = myParsed ? myParsed.key : null;

    if (!standings.length) {
        renderNoteRow("No solves yet — no crews to show.");
        renderCrewNotes(entry, duration, page);
        renderPagination(duration, 1, []);
        return;
    }
    if (!crews.length) {
        renderCrewEmptyState();
        renderCrewNotes(entry, duration, page);
        renderPagination(duration, 1, []);
        return;
    }

    const perPage = 20;
    const pageCount = Math.ceil(crews.length / perPage);
    if (page < 1 || page > pageCount) page = 1;
    const pageCrews = crews.slice((page - 1) * perPage, page * perPage);
    const display = pageCrews.slice();
    if (myCrewKey) {
        const myCrew = crews.find(crew => crew.key === myCrewKey);
        if (myCrew && pageCrews.indexOf(myCrew) === -1) {
            if (myCrew.rank < pageCrews[0].rank) display.unshift(myCrew);
            else display.push(myCrew);
        }
    }
    display.forEach((crew, i) => {
        const row = buildCrewRow(crew, me, myCrewKey);
        if (i % 2 === 0) row.addClass("crew-row-stripe");
        scoreboard.append(row);
    });
    renderCrewNotes(entry, duration, page);
    const pages = [];
    for (let i = 1; i <= pageCount; i++) pages.push(i);
    renderPagination(duration, page, pages);
}

function renderCrewView(duration, page, gen) {
    renderCrewLoading();
    fetchAllStandings(duration, gen).then(entry => {
        if (gen !== scoreboardState.generation) return;
        renderCrewBoard(entry, duration, page);
    }).catch(() => {
        if (gen !== scoreboardState.generation) return;
        $("#scoreboard").empty();
        const warning = renderNoteRow("Failed to load the crew scoreboard. ");
        warning.find(".crew-note").addClass("crew-note-warn");
        const retry = $(`<a role="button" tabindex="0" href="javascript:void(0)">Retry</a>`);
        retry.on("click", () => loadScoreboard(duration, page));
        warning.find(".crew-note").append(retry);
    });
}

function renderHackerView(duration, page, gen) {
    const scoreboard = $("#scoreboard");
    scoreboard.empty().append($(`<tr class="scoreboard-loading"><td colspan="6">Loading...</td></tr>`));
    $("#scoreboard-pages").empty();
    fetchScoreboardPage(duration, page).then(result => {
        if (gen !== scoreboardState.generation) return;
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
        scoreboard.empty();
        const warning = renderNoteRow("Failed to load the scoreboard. ");
        warning.find(".crew-note").addClass("crew-note-warn");
        const retry = $(`<a role="button" tabindex="0" href="javascript:void(0)">Retry</a>`);
        retry.on("click", () => loadScoreboard(duration, page));
        warning.find(".crew-note").append(retry);
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

function setScoreboardView(view) {
    if (scoreboardState.view === view) return;
    scoreboardState.view = view;
    if (history.replaceState) {
        history.replaceState(null, "", view === "crews" ? "#crews" : location.pathname + location.search);
    }
    loadScoreboard(scoreboardState.duration, 1);
}
