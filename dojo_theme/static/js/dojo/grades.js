async function gradeWorkerModule() {
    importScripts("https://cdn.jsdelivr.net/pyodide/v0.27.3/full/pyodide.js");

    const pyodide = await loadPyodide();

    self.onmessage = async (event) => {
        const type = event.data.type;

        if (event.data.type === "load") {
            const { id, code } = event.data;
            try {
                await pyodide.loadPackagesFromImports(event.data.code);
                await pyodide.runPythonAsync(code);
                self.postMessage({ id, type: "loaded" });
            } catch (err) {
                self.postMessage({ id, type: "error", error: err.toString() });
            }
        }

        if (event.data.type === "grade") {
            const { id, data } = event.data;
            try {
                const grade = pyodide.globals.get("grade");
                const grades = JSON.parse(JSON.stringify(grade(pyodide.toPy(data)).toJs()));
                self.postMessage({ id, type: "graded", grades });
            } catch (err) {
                self.postMessage({ id, type: "error", error: err.toString() });
            }
        }
    };

    self.postMessage({ type: "ready" });
}


function createWorker(workerModule) {
    const sandboxedWorkerURL = `data:application/javascript;base64,${btoa("(" + workerModule.toString() + ")()")}`;
    const worker = new Worker(sandboxedWorkerURL);

    worker.onmessage = (event) => {
        if (event.data.type === "error") {
            console.error(event.data.error);
        }
    };

    worker.waitForMessage = (expectedType) =>
        new Promise((resolve) => {
          const handler = (event) => {
            if (event.data.type === expectedType) {
              worker.removeEventListener("message", handler);
              resolve(event.data);
            }
          };
          worker.addEventListener("message", handler);
        });

    return worker;
}


function createAssignmentGradesTable(gradesData) {
    const table = document.createElement("table");
    table.classList.add("table", "table-striped");

    const fields = [];
    gradesData.assignments.forEach(item => {
        Object.keys(item).forEach(key => {
            if (!fields.includes(key))
                fields.push(key);
        });
    });

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    fields.forEach(key => {
        const cell = document.createElement("td");
        cell.textContent = key.replace(/\b\w/g, char => char.toUpperCase());
        headerRow.appendChild(cell);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    gradesData.assignments.forEach(item => {
        const row = document.createElement("tr");
        fields.forEach(key => {
            const cell = document.createElement("td");
            let value = item[key];
            if (value !== undefined && value !== null) {
                if (key === "credit")
                    value = (value * 100).toFixed(2) + "%";
                cell.textContent = value;
            }
            row.appendChild(cell);
        });
        tbody.appendChild(row);
    });
    table.appendChild(tbody);

    return table;
}


async function loadGrades(selector) {
    const gradeWorker = createWorker(gradeWorkerModule);

    const coursePromise = fetch(`/pwncollege_api/v1/dojos/${init.dojo}/course`).then(response => response.json());
    const modulesPromise = fetch(`/pwncollege_api/v1/dojos/${init.dojo}/modules`).then(response => response.json());
    const solvesPromise = fetch(`/pwncollege_api/v1/dojos/${init.dojo}/solves`).then(response => response.json());

    await gradeWorker.waitForMessage("ready");
    const courseData = await coursePromise;

    gradeWorker.postMessage({ type: "load", code: courseData.course.grade_code });
    await gradeWorker.waitForMessage("loaded");

    const [modulesData, solvesData] = await Promise.all([modulesPromise, solvesPromise])
    gradeWorker.postMessage({ type: "grade", data: { course: courseData.course, modules: modulesData.modules, solves: solvesData.solves } });

    const gradesData = (await gradeWorker.waitForMessage("graded")).grades;

    const gradesElement = document.querySelector(selector)
    gradesElement.innerHTML = "";

    const h3 = document.createElement("h3");
    const letterGrade = document.createElement("code");
    letterGrade.textContent = gradesData.overall.letter;
    letterGrade.style.fontSize = "2em";
    h3.append(
        document.createTextNode("Your current grade in the class: "),
        letterGrade,
        document.createTextNode(` (${(gradesData.overall.credit * 100).toFixed(2)}%)`)
    );
    gradesElement.appendChild(h3);

    const gradesTable = createAssignmentGradesTable(gradesData);
    gradesElement.appendChild(gradesTable);
}


async function loadAllGrades(selector) {
    const gradeWorker = createWorker(gradeWorkerModule);

    const coursePromise = fetch(`/pwncollege_api/v1/dojos/${init.dojo}/course`).then(response => response.json());
    const modulesPromise = fetch(`/pwncollege_api/v1/dojos/${init.dojo}/modules`).then(response => response.json());
    const solvesPromise = fetch(`/pwncollege_api/v1/dojos/${init.dojo}/course/solves`).then(response => response.json());
    const studentsPromise = fetch(`/pwncollege_api/v1/dojos/${init.dojo}/course/students`).then(response => response.json());

    await gradeWorker.waitForMessage("ready");
    const courseData = await coursePromise;

    gradeWorker.postMessage({ type: "load", code: courseData.course.grade_code });
    await gradeWorker.waitForMessage("loaded");

    const [modulesData, solvesData, studentsData] = await Promise.all([modulesPromise, solvesPromise, studentsPromise])

    const grades = {};
    for (const [studentToken, student] of Object.entries(studentsData.students)) {
      const course = { ...courseData.course, student: { ...student, token: studentToken } };
      const solves = solvesData.solves.filter(solve => solve.student_token === studentToken);
      gradeWorker.postMessage({ type: "grade", data: { course, modules: modulesData.modules, solves } });
      grades[studentToken] = (await gradeWorker.waitForMessage("graded")).grades;
    }

    const sortedGrades = Object.entries(grades).sort(([_, a], [__, b]) => b.overall.credit - a.overall.credit);

    const gradesElement = document.querySelector(selector)
    gradesElement.innerHTML = "";

    const table = document.createElement("table");
    table.classList.add("table", "table-striped");
    gradesElement.appendChild(table);

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    const studentHeaderCell = document.createElement("td");
    studentHeaderCell.textContent = "Student";
    headerRow.appendChild(studentHeaderCell);
    const gradeHeaderCell = document.createElement("td");
    gradeHeaderCell.textContent = "Grade";
    gradeHeaderCell.style.width = "80%";
    headerRow.appendChild(gradeHeaderCell);
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    sortedGrades.forEach(([studentToken, studentGrades]) => {
        const row = document.createElement("tr");
        const studentCell = document.createElement("td");
        studentCell.textContent = studentToken;
        row.appendChild(studentCell);

        const gradeCell = document.createElement("td");
        const details = document.createElement("details");

        const summary = document.createElement("summary");
        summary.textContent = `${studentGrades.overall.letter} (${(studentGrades.overall.credit * 100).toFixed(2)}%)`;
        details.appendChild(summary);

        const gradesTable = createAssignmentGradesTable(studentGrades);
        details.appendChild(gradesTable);

        gradeCell.appendChild(details);
        row.appendChild(gradeCell);
        tbody.appendChild(row);
    });
    table.appendChild(tbody);
}
