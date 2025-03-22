document.addEventListener('DOMContentLoaded', async () => {
    const container = document.createElement('div');
    container.className = 'activity-graph';
    container.innerHTML = `<h3 style="font-size:16px;">Hacking Activity</h3>
        <div class="grid-container"></div>
        <div class="tooltip"></div>
        <div class="legend">
            <span>Less</span>
            <div class="legend-cells"></div>
            <span>More</span>
        </div>`;
    document.getElementById('activity-tracker').appendChild(container);
    const grid = container.querySelector('.grid-container');
    const tooltip = container.querySelector('.tooltip');
    const now = new Date();
    for (let i = 0; i < 364; i++) {
        const cell = document.createElement('div');
        cell.className = 'activity-cell';
        cell.setAttribute('data-count', 0);
        cell.setAttribute('title', `0 solves`);
        cell.setAttribute('data-date', new Date(now - (i * 86400000)).toISOString().split('T')[0]);
        grid.appendChild(cell);
    }
    const legend = container.querySelector('.legend-cells');
    for (let i = 0; i < 5; i++) {
        const cell = document.createElement('div');
        cell.className = `activity-cell level-${i}`;
        legend.appendChild(cell);
    }
    function updateGrid(dailyActivityData) {
        for (const date in dailyActivityData) {
            const cell = grid.querySelector(`[data-date="${date}"]`);
            if (cell) {
                const count = dailyActivityData[date];
                cell.setAttribute('data-count', count);
                cell.setAttribute('title', `${count} solve(s)`);
                cell.className = `activity-cell level-${ Math.min(4, Math.floor(Math.log(count + 1) / Math.log(2))) }`;
            }
        }
    }
    function countDailySolves(solves) {
        const counts = {};
        solves.forEach(solve => {
            const dateStr = new Date(solve.date).toISOString().split('T')[0];
            counts[dateStr] = (counts[dateStr] || 0) + 1;
        });
        return counts;
    }
    const oneYearAgo = new Date(Date.now() - 364 * 86400000);
    const endpoint = `/api/v1/users/${init.userId}/solves?after=${oneYearAgo.toISOString()}`;
    try {
        const response = await CTFd.fetch(endpoint, {
            method: "GET",
            credentials: "same-origin",
            headers: { "Accept": "application/json" }
        });
        const result = await response.json();
        if (result.success) {
            const allSolves = result.data;
            const dailySolveCount = countDailySolves(allSolves);
            updateGrid(dailySolveCount);
        }
    } catch (err) {
        console.error('Error fetching solves data', err);
    }

    grid.addEventListener('mouseover', (e) => {
        if (e.target.classList.contains('activity-cell')) {
            tooltip.textContent = `${e.target.dataset.date}: ${e.target.dataset.count} solves`;
            tooltip.style.display = 'block';
            tooltip.style.left = `${e.clientX + 10}px`;
            tooltip.style.top = `${e.clientY + 10}px`;
        }
    });
    grid.addEventListener('mouseout', () => {
        tooltip.style.display = 'none';
    });
});
