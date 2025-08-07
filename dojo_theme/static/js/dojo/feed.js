(function() {
    const MAX_EVENTS = 50;
    let eventSource = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;
    const RECONNECT_DELAY = 3000;
    
    function escapeHtml(unsafe) {
        if (!unsafe) return '';
        return String(unsafe)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
    
    function formatTimestamp(timestamp) {
        return new Date(timestamp).toISOString().slice(0, 19).replace('T', ' ');
    }
    
    function renderLink(href, text, escape = true) {
        if (!href) return escape ? escapeHtml(text) : text;
        return `<a href="${escapeHtml(href)}">${escape ? escapeHtml(text) : text}</a>`;
    }
    
    function renderDojoLink(data) {
        const name = data.dojo_name || data.dojo_id;
        return name ? renderLink(`/dojos/${data.dojo_id}`, name) + ' / ' : '';
    }
    
    function renderModuleLink(data) {
        if (!data.module_name) return '';
        const href = data.dojo_id && data.module_id ? `/${data.dojo_id}/${data.module_id}` : null;
        return renderLink(href, data.module_name) + ' / ';
    }
    
    function renderChallengeLink(data) {
        const href = data.dojo_id && data.module_id && data.challenge_id 
            ? `/${data.dojo_id}/${data.module_id}#${data.challenge_id}` : null;
        return renderLink(href, `<strong>${escapeHtml(data.challenge_name)}</strong>`, false);
    }
    
    function formatUserName(event) {
        let html = '';
        if (event.user_belt) {
            const title = event.user_belt.charAt(0).toUpperCase() + event.user_belt.slice(1) + ' Belt';
            html += `<img src="/belt/${event.user_belt}.svg" class="scoreboard-belt" 
                     style="height: 1.5em; vertical-align: middle; margin-right: 0.25em;" title="${title}"> `;
        }
        html += escapeHtml(event.user_name);
        if (event.user_emojis?.length > 0) {
            event.user_emojis.slice(0, 3).forEach(e => html += ` <span title="${e}">${e}</span>`);
            if (event.user_emojis.length > 3) html += ` <small class="text-muted">+${event.user_emojis.length - 3}</small>`;
        }
        return html;
    }
    
    function renderUser(event) {
        return `<strong>${renderLink(`/hacker/${event.user_name}`, formatUserName(event), false)}</strong>`;
    }
    
    const eventRenderers = {
        container_start: (event) => ({
            icon: '<i class="fas fa-play-circle fa-2x text-primary"></i>',
            content: `${renderUser(event)} started a 
                <span class="badge bg-${event.data.mode === 'practice' ? 'warning' : 'primary'}">${escapeHtml(event.data.mode)}</span>
                container for ${renderDojoLink(event.data)}${renderModuleLink(event.data)}${renderChallengeLink(event.data)}`
        }),
        challenge_solve: (event) => ({
            icon: '<i class="fas fa-flag-checkered fa-2x text-success"></i>',
            content: `${renderUser(event)} solved ${renderDojoLink(event.data)}${renderModuleLink(event.data)}${renderChallengeLink(event.data)}
                ${event.data.first_blood ? ' <span class="badge bg-danger">FIRST BLOOD!</span>' : ''}`
        }),
        emoji_earned: (event) => ({
            icon: `<span style="font-size: 2em;">${event.data.emoji}</span>`,
            content: `${renderUser(event)} earned the <strong>${event.data.emoji}</strong> emoji!
                ${event.data.dojo_name || event.data.dojo_id ? 
                    `<br><small class="text-muted">Completed ${renderLink(`/dojos/${event.data.dojo_id}`, 
                     event.data.dojo_name || event.data.dojo_id)}</small>` :
                    `<br><small class="text-muted">${escapeHtml(event.data.reason)}</small>`}`
        }),
        belt_earned: (event) => ({
            icon: '<i class="fas fa-award fa-2x text-warning"></i>',
            content: `${renderUser(event)} earned their <strong>${escapeHtml(event.data.belt_name)}</strong>!
                ${event.data.dojo_name || event.data.dojo_id ? 
                    `<br><small class="text-muted">Completed ${renderLink(`/dojos/${event.data.dojo_id}`,
                     event.data.dojo_name || event.data.dojo_id)}</small>` : ''}`
        }),
        dojo_update: (event) => ({
            icon: '<i class="fas fa-sync-alt fa-2x text-info"></i>',
            content: `${renderUser(event)} updated ${renderLink(`/dojos/${event.data.dojo_id}`, 
                event.data.dojo_name || event.data.dojo_id)}
                <br><small class="text-muted">${escapeHtml(event.data.summary)}</small>`
        })
    };
    
    function createEventCard(event) {
        const card = document.createElement('div');
        card.className = 'event-card card mb-3 bg-dark text-white border-secondary';
        card.dataset.eventId = event.id;
        card.style.opacity = '0';
        
        const renderer = eventRenderers[event.type];
        if (!renderer) return card;
        
        const {icon, content} = renderer(event);
        card.innerHTML = `
            <div class="card-body">
                <div class="d-flex align-items-center">
                    <div class="event-icon me-4" style="min-width: 50px;">${icon}</div>
                    <div class="flex-grow-1">
                        <div class="event-content">${content}</div>
                        <small class="text-muted event-time" data-timestamp="${event.timestamp}">
                            ${formatTimestamp(event.timestamp)}
                        </small>
                    </div>
                </div>
            </div>`;
        return card;
    }
    
    function addEvent(event) {
        const eventsList = document.getElementById('events-list');
        if (document.querySelector(`[data-event-id="${event.id}"]`)) return;
        
        const emptyMessage = eventsList.parentElement.querySelector('.text-center.text-muted');
        if (emptyMessage) emptyMessage.remove();
        
        const card = createEventCard(event);
        eventsList.insertBefore(card, eventsList.firstChild);
        
        setTimeout(() => {
            card.style.transition = 'opacity 0.5s ease-in';
            card.style.opacity = '1';
        }, 10);
        
        const allCards = eventsList.querySelectorAll('.event-card');
        if (allCards.length > MAX_EVENTS) {
            Array.from(allCards).slice(MAX_EVENTS).forEach(card => {
                card.style.transition = 'opacity 0.3s ease-out';
                card.style.opacity = '0';
                setTimeout(() => card.remove(), 300);
            });
        }
    }
    
    function updateConnectionStatus(status, message) {
        const statusDiv = document.getElementById('connection-status');
        const messageSpan = document.getElementById('connection-message');
        
        if (status === 'connected') {
            statusDiv.style.display = 'none';
        } else {
            statusDiv.style.display = 'block';
            statusDiv.className = `alert ${status === 'error' ? 'alert-danger' : 'alert-info'} mb-3`;
            messageSpan.textContent = message;
        }
    }
    
    function connectSSE() {
        if (eventSource) eventSource.close();
        
        updateConnectionStatus('connecting', 'Connecting to live feed...');
        eventSource = new EventSource('/pwncollege_api/v1/feed/stream');
        
        eventSource.onopen = () => {
            reconnectAttempts = 0;
            updateConnectionStatus('connected', '');
        };
        
        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'connected') {
                    updateConnectionStatus('connected', '');
                } else if (data.type !== 'heartbeat') {
                    addEvent(data);
                }
            } catch (e) {
                console.error('Failed to parse event:', e);
            }
        };
        
        eventSource.onerror = () => {
            eventSource.close();
            if (++reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
                updateConnectionStatus('error', 'Connection lost. Please refresh the page.');
            } else {
                updateConnectionStatus('error', `Connection lost. Reconnecting in ${RECONNECT_DELAY / 1000} seconds...`);
                setTimeout(connectSSE, RECONNECT_DELAY);
            }
        };
    }
    
    function updateTimestamps() {
        document.querySelectorAll('.event-time').forEach(elem => {
            const timestamp = elem.dataset.timestamp;
            if (timestamp) elem.textContent = formatTimestamp(timestamp);
        });
    }
    
    document.addEventListener('DOMContentLoaded', () => {
        updateTimestamps();
        setInterval(updateTimestamps, 60000);
        connectSSE();
        
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && eventSource) {
                eventSource.close();
            } else if (!document.hidden && (!eventSource || eventSource.readyState === EventSource.CLOSED)) {
                connectSSE();
            }
        });
    });
    
    window.addEventListener('beforeunload', () => {
        if (eventSource) eventSource.close();
    });
})();