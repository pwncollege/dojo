document.addEventListener('DOMContentLoaded', async () => {
    const tracker = document.getElementById('activity-tracker');
    if (!tracker) return;
    const userID = tracker.getAttribute('user-id');
    const container = document.createElement('div');
    container.className = 'activity-graph';
    container.innerHTML = `<h3 style="font-size:0.9rem; text-align:left; padding-left:2px;">Hacking Activity</h3>
        <div class="streak" style="overflow=hidden";></div>
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

    function getLocalISODate(date) {
        const tzOffset = date.getTimezoneOffset() * 60000;
        return new Date(date.getTime() - tzOffset).toISOString().split('T')[0];
    }
    
    for (let i = 363; i >= 0; i--) {
        const cell = document.createElement('div');
        cell.className = 'activity-cell';
        const cellDate = new Date(Date.now() - i * 86400000);
        const formattedDate = getLocalISODate(cellDate);
        const displayDate = cellDate.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
        cell.setAttribute('data-count', 0);
        cell.setAttribute('data-date', formattedDate);
        cell.setAttribute('data-display-date', displayDate);
        cell.setAttribute('title', `${displayDate}: 0 solves`);
        container.querySelector('.grid-container').appendChild(cell);
        const currentMonth = cellDate.toLocaleDateString('en-US', { month: 'short' });
        if(currentMonth !== container.querySelector('.month-labels').lastChild?.textContent &&
           (currentMonth !== container.querySelector('.month-labels').childNodes[0]?.textContent)) {
            const monthLabel = document.createElement('span');
            monthLabel.className = 'month-label';
            monthLabel.textContent = currentMonth;
            monthLabel.style.left = `${(Math.ceil((363 - i) / 7) * 12)}px`;
            container.querySelector('.month-labels').appendChild(monthLabel);
        }
    }
    
    for (let i = 0; i < 5; i++) {
        const cell = document.createElement('div');
        cell.className = `activity-cell level-${i}`;
        container.querySelector('.legend-cells').appendChild(cell);
    }
    
    function updateGrid(dailyActivityData, max) {
        for (const date in dailyActivityData) {
            const cell = container.querySelector('.grid-container').querySelector(`[data-date="${date}"]`);
            if (cell) {
                const count = dailyActivityData[date];
                const displayDate = cell.dataset.displayDate;
                const solveText = count === 1 ? 'solve' : 'solves';
                cell.setAttribute('data-count', count);
                cell.setAttribute('title', `${displayDate}: ${count} ${solveText}`);
                let level = 0;
                if(count > 0) {
                    if((count/ max) > 0.75) level = 4;
                    else if((count/ max) > 0.5) level = 3;
                    else if((count/ max) > 0.25) level = 2;
                    else if((count/ max) > 0 ) level = 1;
                }    
                cell.className = `activity-cell level-${level}`;
            }
        }
    }
    
    function countDailySolves(solves) {
        const counts = {};
        solves.forEach(solve => {
            const dateStr = getLocalISODate(new Date(solve.date));
            counts[dateStr] = (counts[dateStr] || 0) + 1;
        });
        return counts;
    }

    function getStreak(dailyActivityData) {
        let streak = 0;
        for (let offset = 0; offset < 364; offset++) {
            const date = new Date(Date.now() - offset * 86400000);
            const formatted = getLocalISODate(date);
            if (dailyActivityData[formatted] && dailyActivityData[formatted] > 0) {
                streak++;
            } else {
                break;
            }
        }
        return streak;
    }
    
    const oneYearAgo = new Date(Date.now() - 364 * 86400000);
    const endpoint = `/api/v1/users/${userID}/solves?after=${oneYearAgo.toISOString()}`;
    CTFd.fetch(endpoint, {
        method: "GET",
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
    })
    .then(response => response.json())
    .then(result => {
        if(result.success) {
            const dailySolveCount = countDailySolves(result.data);
            const max = Math.max(...Object.values(dailySolveCount), 1);
            updateGrid(dailySolveCount, max);
            const streak = getStreak(dailySolveCount);
            container.querySelector('.streak').textContent = streak > 0 ? `${streak} day streak` : '';
        }
    })
    .catch(err => {
        console.error('Error fetching solves data', err);
    });
});
