document.addEventListener('DOMContentLoaded', async () => {
    const tracker = document.getElementById('activity-tracker');
    if (!tracker) return;
    const userID = tracker.getAttribute('user-id');
    const container = document.createElement('div');
    container.className = 'activity-graph';
    container.innerHTML = `<h3>Hacking Activity</h3>
        <div class="streak"></div>
        <div class="grid-wrapper">
        <div class="month-labels" style="font-size:0.7rem; height: 16px; position: relative;"></div>
        <div class="grid-container"></div>
        </div>
        <div class="legend">
            <span>Less</span>
            <div class="legend-cells"></div>
            <span>More</span>
        </div>`;
    tracker.appendChild(container);

    const grid = container.querySelector('.grid-container');
    const monthLabels = container.querySelector('.month-labels');
    const legendCells = container.querySelector('.legend-cells');
    const streak = container.querySelector('.streak');

    function getLocalISODate(date) {
        const tzOffset = date.getTimezoneOffset() * 60000;
        return new Date(date.getTime() - tzOffset).toISOString().split('T')[0];
    }
    
    const now = Date.now();
    let monthCount = 1;
    for (let i = 363; i >= 0; i--) {
        const cell = document.createElement('div');
        cell.className = 'activity-cell';
        const cellDate = new Date(now - i * 86400000);
        const formattedDate = getLocalISODate(cellDate);
        const displayDate = cellDate.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
        cell.dataset.count = 0;
        cell.dataset.date = formattedDate;
        cell.dataset.displayDate = displayDate;
        cell.title = `${displayDate}: 0 solves`;
        grid.appendChild(cell);
        const currentMonth = cellDate.toLocaleDateString('en-US', { month: 'short' });
        if(currentMonth !== monthLabels.lastChild?.textContent &&
           (currentMonth !== monthLabels.childNodes[0]?.textContent)) {
            const monthLabel = document.createElement('span');
            monthLabel.id = `month-label-${monthCount++}`;
            monthLabel.className = 'month-label';
            monthLabel.textContent = currentMonth;
            monthLabel.style.left = `${(Math.ceil((363 - i) / 7) * 12)}px`;
            monthLabels.appendChild(monthLabel);
        }
    }

    if (document.getElementById('month-label-1').getBoundingClientRect().right >
        document.getElementById('month-label-2').getBoundingClientRect().left) {
        document.getElementById('month-label-1').style.display = 'none';
    }

    for (let i = 0; i < 5; i++) {
        const cell = document.createElement('div');
        cell.className = `activity-cell level-${i}`;
        legendCells.appendChild(cell);
    }
    
    function updateGrid(dailyActivityData, max) {
        for (const date in dailyActivityData) {
            const cell = grid.querySelector(`[data-date="${date}"]`);
            if (cell) {
                const count = dailyActivityData[date];
                const displayDate = cell.dataset.displayDate;
                const solveText = count === 1 ? 'solve' : 'solves';
                cell.dataset.count = count;
                cell.title = `${displayDate}: ${count} ${solveText}`;
                let level = 0;
                const ratio = count / max;
                if(count > 0) {
                    if(ratio > 0.75) level = 4;
                    else if(ratio > 0.5) level = 3;
                    else if(ratio > 0.25) level = 2;
                    else if(ratio > 0 ) level = 1;
                }
                cell.className = `activity-cell level-${level}`;
            }
        }
    }

    function countDailySolves(timestamps) {
        const counts = {};
        timestamps.forEach(ts => {
            const dateStr = getLocalISODate(new Date(ts));
            counts[dateStr] = (counts[dateStr] || 0) + 1;
        });
        return counts;
    }

    function getStreak(dailyActivityData) {
        let streak = 0;
        for (let offset = 0; offset < 364; offset++) {
            const date = new Date(now - offset * 86400000);
            const formatted = getLocalISODate(date);
            if (dailyActivityData[formatted] && dailyActivityData[formatted] > 0) {
                streak++;
            } else {
                break;
            }
        }
        return streak;
    }

    const endpoint = `/pwncollege_api/v1/activity/${userID}`;
    CTFd.fetch(endpoint, {
        method: "GET",
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
    })
    .then(response => response.json())
    .then(result => {
        if(result.success) {
            const dailySolveCount = countDailySolves(result.data.solve_timestamps || []);
            const max = Math.max(...Object.values(dailySolveCount), 1);
            updateGrid(dailySolveCount, max);
            const streakText = getStreak(dailySolveCount);
            streak.textContent = streakText > 0 ? `${streakText} day streak` : '';
        }
    })
    .catch(err => {
        console.error('Error fetching activity data', err);
    });
});
