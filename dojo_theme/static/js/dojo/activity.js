document.addEventListener('DOMContentLoaded', () => {
    const container = document.createElement('div');
    container.className = 'activity-graph';
    container.innerHTML = `
        <h2>Hacking Activity</h2>
        <div class="grid-container"></div>
        <div class="tooltip"></div>
        <div class="legend">
            <span>Less</span>
            <div class="legend-cells"></div>
            <span>More</span>
        </div>
    `;

    // Insert into DOM (adjust selector based on where you want it)
    document.getElementById('activity-tracker').appendChild(container);

    // Generate grid cells
    const grid = container.querySelector('.grid-container');
    const tooltip = container.querySelector('.tooltip');
    const now = new Date();
    
    // 364 days
    for (let i = 0; i < 364; i++) {
        const cell = document.createElement('div');
        cell.className = 'activity-cell';
        cell.setAttribute('data-count', 0);
        cell.setAttribute('data-date', new Date(now - (i * 86400000)).toISOString().split('T')[0]);
        grid.appendChild(cell);
    }

    // Legend Cells
    const legend = container.querySelector('.legend-cells');
    for (let i = 0; i < 5; i++) {
        const cell = document.createElement('div');
        cell.className = `activity-cell level-${i}`;
        legend.appendChild(cell);
    }

    // Fetch activity data need endpoint
    fetch('/api/activity-data')
        .then(response => response.json())
        .catch(() => {
            const mockData = [];
            const today = new Date();
            for(let i = 0; i < 365; i++){
                const date = new Date(today);
                date.setDate(date.getDate() - i);
                mockData.push({
                    date: date.toISOString().split('T')[0],
                    count: Math.floor(Math.random() * 10)
                });
            } 
            return Promise.resolve(mockData);
        })
        .then(data => {
            data.forEach(entry => {
                const cell = grid.querySelector(`[data-date="${entry.date}"]`);
                if (cell) {
                    cell.setAttribute('data-count', entry.count);
                    cell.className = `activity-cell level-${getLevel(entry.count)}`;
                }
            });
        });

    // Tooltip stuff
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

    function getLevel(count) {
        return Math.min(4, Math.floor(Math.log(count + 1) / Math.log(2)));
    }
});