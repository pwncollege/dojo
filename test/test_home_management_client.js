const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../site/theme/static/js/dojo/settings.js"), "utf8").split("$(() => {")[0];
const client = fs.readFileSync(path.join(__dirname, "../site/theme/static/js/dojo/util.js"), "utf8").split("$.fn.serializeJSON")[0];

async function exercise(action, response, accepted = true) {
    const events = [];
    let message;
    let disabled;
    const results = {
        html: () => results,
        find: () => ({ text: value => { message = value; } }),
    };
    const context = vm.createContext({
        $: selector => selector === "#home-management-results" ? results : {
            prop: (name, value) => { disabled = value; events.push([name, value]); },
        },
        confirm: () => accepted,
        init: { urlRoot: "", csrfNonce: "test-nonce" },
        fetch: async (url, options) => {
            events.push(["fetch", url, options]);
            if (response instanceof Error) throw response;
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

function archive(status = "success", message = "Home backup downloaded.") {
    return new Response(new Uint8Array([1, 2, 3]), { status: status === "failed" ? 500 : status === "unknown" ? 503 : 200, headers: {
        "Content-Type": "application/gzip",
        "X-Home-Operation-Status": status,
        "X-Home-Operation-Message": message,
        "X-Home-Backup-Skipped-Files": "2",
    } });
}

(async () => {
    for (const action of ["backup", "reset"]) {
        const result = await exercise(action, archive());
        const request = result.events.find(event => event[0] === "fetch");
        assert.equal(request[1], `/pwncollege_api/v1/workspace/${action}_home`);
        assert.equal(request[2].method, "POST");
        assert.equal(request[2].credentials, "same-origin");
        assert.equal(request[2].body, "{}");
        assert.equal(request[2].headers["CSRF-Token"], "test-nonce");
        assert.ok(result.events.some(event => event[0] === "download"));
        assert.ok(result.events.some(event => event[0] === "filename" && event[1] === "home-backup.tar.gz"));
        assert.match(result.message, /2 file\(s\) larger than 10 MB/);
        assert.equal(result.disabled, false);
    }
    const cancelled = await exercise("reset", archive(), false);
    assert.equal(cancelled.events.length, 0);
    const limited = await exercise("backup", new Response(JSON.stringify({ error: "Three times per hour" }), {
        status: 429, headers: { "Content-Type": "application/json" },
    }));
    assert.equal(limited.message, "Three times per hour");
    assert.equal(limited.disabled, false);
    assert.ok(!limited.events.some(event => event[0] === "download"));
    const failed = await exercise("reset", archive("failed", "The reset failed. Please try again."));
    assert.ok(failed.events.some(event => event[0] === "download"));
    assert.match(failed.message, /Backup download started.*reset failed/);
    const unknown = await exercise("reset", archive("unknown", "Wait 10 minutes before trying again."));
    assert.ok(unknown.events.some(event => event[0] === "download"));
    assert.match(unknown.message, /Wait 10 minutes/);
    const disconnected = await exercise("reset", new Error("Connection lost"));
    assert.equal(disconnected.message, "Connection lost");
    assert.equal(disconnected.disabled, false);
    console.log("Home Management client flows passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
