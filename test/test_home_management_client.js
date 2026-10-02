const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../site/theme/static/js/dojo/settings.js"), "utf8").split("$(() => {")[0];
const client = fs.readFileSync(path.join(__dirname, "../site/theme/static/js/dojo/util.js"), "utf8").split("$.fn.serializeJSON")[0];

async function exercise(action, responses, accepted = true) {
    const events = [];
    let message, disabled;
    const results = { html: () => results, find: () => ({ text: value => { message = value; } }) };
    const context = vm.createContext({
        $: selector => selector === "#home-management-results" ? results : {
            prop: (name, value) => { disabled = value; },
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
    await context.home_download_and_show(action);
    return { events, message, disabled };
}

const archive = body => new Response(body || new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "application/gzip" } });
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

(async () => {
    for (const action of ["backup", "reset"]) {
        const result = await exercise(action, [archive(), json({ success: true })]);
        const requests = result.events.filter(event => event[0] === "fetch");
        assert.deepEqual(requests.map(event => event[1]), action === "reset"
            ? ["/pwncollege_api/v1/workspace/backup_home", "/pwncollege_api/v1/workspace/reset_home"]
            : ["/pwncollege_api/v1/workspace/backup_home"]);
        for (const request of requests) {
            assert.equal(request[2].method, "POST");
            assert.equal(request[2].body, "{}");
            assert.equal(request[2].headers["CSRF-Token"], "test-nonce");
        }
        assert.ok(result.events.some(event => event[0] === "filename" && event[1] === "home-backup.tar.gz"));
        if (action === "reset") {
            const deletion = result.events.findIndex(event => event[1]?.endsWith("reset_home"));
            assert.ok(result.events.findIndex(event => event[0] === "received") < deletion);
            assert.ok(result.events.findIndex(event => event[0] === "download") < deletion);
        }
        assert.equal(result.disabled, false);
    }
    assert.equal((await exercise("reset", [], false)).events.length, 0);
    for (const response of [json({ error: "Three times per hour" }, 429), new Error("Connection lost"), archive(new ReadableStream({
        start(controller) { controller.error(new Error("Incomplete download")); },
    }))]) {
        const result = await exercise("reset", [response]);
        assert.equal(result.events.filter(event => event[0] === "fetch").length, 1);
        assert.ok(!result.events.some(event => event[0] === "download"));
        assert.equal(result.disabled, false);
    }
    const restarted = await exercise("reset", [archive(), json({ success: false, error: "A workspace is active" }, 409)]);
    assert.ok(restarted.events.some(event => event[0] === "download"));
    assert.equal(restarted.message, "Backup downloaded. A workspace is active");
    const failed = await exercise("reset", [archive(), new Error("Connection lost")]);
    assert.ok(failed.events.some(event => event[0] === "download"));
    assert.equal(failed.disabled, false);
    console.log("Home Management client flows passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
