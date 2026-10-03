const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../site/theme/static/js/dojo/settings.js"), "utf8").split("$(() => {")[0];
const client = fs.readFileSync(path.join(__dirname, "../site/theme/static/js/dojo/util.js"), "utf8").split("$.fn.serializeJSON")[0];

async function exercise(actions, responses, accepted = true) {
    const events = [];
    const states = [];
    const disabled = { "#backup-home-button": false, "#reset-home-button": true };
    let message;
    const results = { html: () => results, find: () => ({ text: value => { message = value; } }) };
    const context = vm.createContext({
        $: selector => selector === "#home-management-results" ? results : {
            prop: (name, value) => { for (const id of selector.split(", ")) disabled[id] = value; },
        },
        confirm: () => accepted,
        init: { urlRoot: "", csrfNonce: "test-nonce" },
        fetch: async (url, options) => {
            events.push(["fetch", url, options]);
            const response = responses.shift();
            if (response instanceof Error) throw response;
            if (url.endsWith("backup_home")) {
                const blob = response.blob.bind(response);
                response.blob = async () => { const data = await blob(); events.push(["received"]); return data; };
            }
            return response;
        },
        document: {
            createElement: () => ({ click: () => events.push(["download"]), remove: () => {} }),
            body: { appendChild: link => events.push(["filename", link.download]) },
        },
        URL: { createObjectURL: () => "blob:test", revokeObjectURL: () => {} },
        setTimeout: callback => callback(),
    });
    context.window = context;
    vm.runInContext(client, context);
    vm.runInContext(source, context);
    for (const action of actions) {
        await context.home_manage_and_show(action);
        states.push({ ...disabled });
    }
    return { events, message, disabled, states };
}

const archive = body => new Response(body || new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "application/gzip" } });
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

(async () => {
    for (const actions of [["backup"], ["backup", "reset", "reset"]]) {
        const result = await exercise(actions, [archive(), json({ success: true })]);
        const requests = result.events.filter(event => event[0] === "fetch");
        assert.deepEqual(requests.map(event => event[1]), actions.includes("reset")
            ? ["/pwncollege_api/v1/workspace/backup_home", "/pwncollege_api/v1/workspace/reset_home"]
            : ["/pwncollege_api/v1/workspace/backup_home"]);
        for (const request of requests) {
            assert.equal(request[2].method, "POST");
            assert.equal(request[2].body, "{}");
            assert.equal(request[2].headers["CSRF-Token"], "test-nonce");
        }
        assert.ok(result.events.some(event => event[0] === "filename" && event[1] === "home-backup.tar.gz"));
        assert.equal(result.events.filter(event => event[0] === "download").length, 1);
        assert.equal(result.states[0]["#reset-home-button"], false);
        if (actions.includes("reset")) {
            const deletion = result.events.findIndex(event => event[1]?.endsWith("reset_home"));
            assert.ok(result.events.findIndex(event => event[0] === "received") < deletion);
            assert.ok(result.events.findIndex(event => event[0] === "download") < deletion);
            assert.equal(result.disabled["#reset-home-button"], true);
        }
        assert.equal(result.disabled["#backup-home-button"], false);
    }
    assert.equal((await exercise(["reset"], [])).events.length, 0);
    const canceled = await exercise(["backup", "reset"], [archive()], false);
    assert.equal(canceled.events.filter(event => event[0] === "fetch").length, 1);
    assert.equal(canceled.disabled["#reset-home-button"], false);
    for (const response of [json({ error: "Three times per hour" }, 429), json({ success: true }), new Error("Connection lost"), archive(new ReadableStream({
        start(controller) { controller.error(new Error("Incomplete download")); },
    }))]) {
        const result = await exercise(["backup", "reset"], [response]);
        assert.equal(result.events.filter(event => event[0] === "fetch").length, 1);
        assert.ok(!result.events.some(event => event[0] === "download"));
        assert.equal(result.disabled["#backup-home-button"], false);
        assert.equal(result.disabled["#reset-home-button"], true);
    }
    const restarted = await exercise(["backup", "reset", "reset"], [archive(), json({ success: false, error: "A workspace is active" }, 409)]);
    assert.ok(restarted.events.some(event => event[0] === "download"));
    assert.equal(restarted.message, "A workspace is active");
    assert.equal(restarted.events.filter(event => event[0] === "fetch").length, 2);
    assert.equal(restarted.disabled["#reset-home-button"], true);
    const failed = await exercise(["backup", "reset"], [archive(), new Error("Connection lost")]);
    assert.ok(failed.events.some(event => event[0] === "download"));
    assert.equal(failed.disabled["#backup-home-button"], false);
    assert.equal(failed.disabled["#reset-home-button"], true);
    const replacement = await exercise(["backup", "backup", "reset"], [archive(), new Error("Connection lost")]);
    assert.equal(replacement.events.filter(event => event[0] === "fetch").length, 2);
    assert.equal(replacement.disabled["#reset-home-button"], true);
    console.log("Home Management client flows passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
