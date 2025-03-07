async function workerModule() {
    importScripts("https://cdn.jsdelivr.net/pyodide/v0.27.3/full/pyodide.js");

    const pyodide = await loadPyodide();

    self.onmessage = async (event) => {
        const { code, data } = event.data;
        await pyodide.loadPackagesFromImports(code);
        try {
            await pyodide.runPythonAsync(code);
            const grade = pyodide.globals.get("grade");
            const result = JSON.parse(JSON.stringify(grade(pyodide.toPy(data)).toJs()));
            self.postMessage({ type: "result", result });
        } catch (err) {
            self.postMessage({ type: "error", error: err.toString() });
        }
    };

    self.postMessage({ type: "ready" });
}


function renderGrades(gradesData) {
    const grades = document.getElementById("grades");
    grades.innerHTML = "";

    const h1 = document.createElement("h1");
    h1.textContent = `Your current grade in the class: ${gradesData.overall.letter} (${(gradesData.overall.credit * 100).toFixed(2)}%)`;
    grades.appendChild(h1);

    const table = document.createElement("table");
    grades.appendChild(table);

    const headerRow = document.createElement("tr");
    Object.keys(gradesData.assignments[0]).forEach(headerText => {
        const th = document.createElement("th");
        th.textContent = headerText.replace(/\b\w/g, char => char.toUpperCase());
        headerRow.appendChild(th);
    });
    table.appendChild(headerRow);

    gradesData.assignments.forEach(item => {
        const row = document.createElement("tr");
        Object.keys(item).forEach(key => {
            const cell = document.createElement("td");
            let value = item[key];
            if (key == "credit")
                value = (value * 100).toFixed(2) + "%";
            cell.textContent = value;
            row.appendChild(cell);
        });
        table.appendChild(row);
    });

}


document.addEventListener("DOMContentLoaded", () => {
    // TODO: Remove feature flag when this feature is ready
    if (!window.location.search.includes("local"))
        return;

    const workerBlob = new Blob(["(" + workerModule.toString() + ")()"], { type: "application/javascript" });
    const workerURL = URL.createObjectURL(workerBlob);
    const worker = new Worker(workerURL);

    worker.onmessage = (event) => {
        if (event.data.type === "error") {
            console.error(event.data.error);
        }

        if (event.data.type === "result") {
            if (!event.data.result)
                return;
            renderGrades(event.data.result);
        }
    };

    const workerReadyPromise = new Promise((resolve) => {
        const onMessageHandler = (event) => {
            if (event.data.type === "ready") {
                resolve();
                worker.removeEventListener("message", onMessageHandler);
            }
        };
        worker.addEventListener("message", onMessageHandler);
    });

    Promise.all([
        workerReadyPromise,
        fetch(`/${init.dojo}/grade.py`).then(response => response.text()),
        fetch(`/pwncollege_api/v1/dojos/${init.dojo}/modules`).then(response => response.json()),
        fetch(`/pwncollege_api/v1/dojos/${init.dojo}/solves`).then(response => response.json()),
    ]).then(([_, code, modulesData, solvesData]) => {
        const data = { modules: modulesData.modules, solves: solvesData.solves, student: {} };
        worker.postMessage({ code, data });
    }).catch(error => {
        console.error("Error:", error);
    });
});
