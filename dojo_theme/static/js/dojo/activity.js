document.addEventListener('DOMContentLoaded', async () => {
    const tracker = document.getElementById('activity-tracker');
    if (!tracker) return;
    const container = document.createElement('div');
    container.className = 'activity-graph';
    container.innerHTML = `<h3 style="font-size:16px; text-align:left;">Hacking Activity</h3>
        <div class="streak"></div>
        <div class="grid-container"></div>
        <div class="legend">
            <span>Less</span>
            <div class="legend-cells"></div>
            <span>More</span>
        </div>`;
    tracker.appendChild(container);
    
    const grid = container.querySelector('.grid-container');
    
    for (let i = 363; i >= 0; i--) {
        const cell = document.createElement('div');
        cell.className = 'activity-cell';
        const cellDate = new Date(Date.now() - i * 86400000);
        const formattedDate = cellDate.toISOString().split('T')[0];
        const displayDate = cellDate.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
        cell.setAttribute('data-count', 0);
        cell.setAttribute('data-date', formattedDate);
        cell.setAttribute('data-display-date', displayDate);
        cell.setAttribute('title', `${displayDate}: 0 solves`);
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
                const displayDate = cell.dataset.displayDate;
                const solveText = count === 1 ? 'solve' : 'solves';
                cell.setAttribute('data-count', count);
                cell.setAttribute('title', `${displayDate}: ${count} ${solveText}`);
                cell.className = `activity-cell level-${Math.min(4, Math.floor(Math.log(count + 1) / Math.log(2)))}`;
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

    function getStreak(dailyActivityData) {
        let streak = 0;
        for (let offset = 0; offset < 364; offset++) {
            const date = new Date(Date.now() - offset * 86400000);
            const formatted = date.toISOString().split('T')[0];
            if (dailyActivityData[formatted] && dailyActivityData[formatted] > 0) {
                streak++;
            } else {
                break;
            }
        }
        return streak;
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
            const dailySolveCount = countDailySolves(result.data);
            updateGrid(dailySolveCount);
            const streak = getStreak(dailySolveCount);
            const streakDiv = container.querySelector('.streak');
            streakDiv.textContent = streak > 0 ? `${streak} day streak` : '';
        }
    } catch (err) {
        console.error('Error fetching solves data', err);
    }
});
