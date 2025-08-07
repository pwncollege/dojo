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
        const date = new Date(timestamp);
        
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const seconds = String(date.getSeconds()).padStart(2, '0');
        
        return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    }
    
    function formatUserName(event) {
        let userHtml = '';
        
        if (event.user_belt) {
            const beltTitle = event.user_belt.charAt(0).toUpperCase() + event.user_belt.slice(1) + ' Belt';
            userHtml += `<img src="/belt/${event.user_belt}.svg" 
                              class="scoreboard-belt" 
                              style="height: 1.5em; vertical-align: middle; margin-right: 0.25em;"
                              title="${beltTitle}"> `;
        }
        
        userHtml += escapeHtml(event.user_name);
        
        if (event.user_emojis && event.user_emojis.length > 0) {
            const displayEmojis = event.user_emojis.slice(0, 3);
            displayEmojis.forEach(emoji => {
                userHtml += ` <span title="${emoji}">${emoji}</span>`;
            });
            
            if (event.user_emojis.length > 3) {
                userHtml += ` <small class="text-muted">+${event.user_emojis.length - 3}</small>`;
            }
        }
        
        return userHtml;
    }
    
    function updateTimestamps() {
        document.querySelectorAll('.event-time').forEach(elem => {
            const timestamp = elem.dataset.timestamp;
            if (timestamp) {
                elem.textContent = formatTimestamp(timestamp);
            }
        });
    }
    
    function createEventCard(event) {
        const card = document.createElement('div');
        card.className = 'event-card card mb-3 bg-dark text-white border-secondary';
        card.dataset.eventId = event.id;
        card.style.opacity = '0';
        
        let iconHtml = '';
        let contentHtml = '';
        
        switch(event.type) {
            case 'container_start':
                iconHtml = '<i class="fas fa-play-circle fa-2x text-primary"></i>';
                const modeClass = event.data.mode === 'practice' ? 'warning' : 'primary';
                contentHtml = `
                    <strong><a href="/hacker/${escapeHtml(event.user_name)}">${formatUserName(event)}</a></strong>
                    started a 
                    <span class="badge bg-${modeClass}">${escapeHtml(event.data.mode)}</span>
                    container for
                    ${event.data.dojo_name ? ` <a href="/dojos/${escapeHtml(event.data.dojo_id)}">${escapeHtml(event.data.dojo_name)}</a> /` : 
                       (event.data.dojo_id ? ` <a href="/dojos/${escapeHtml(event.data.dojo_id)}">${escapeHtml(event.data.dojo_id)}</a> /` : '')}
                    ${event.data.module_name ? 
                        (event.data.dojo_id && event.data.module_id ? 
                            ` <a href="/${escapeHtml(event.data.dojo_id)}/${escapeHtml(event.data.module_id)}">${escapeHtml(event.data.module_name)}</a> /` : 
                            ` ${escapeHtml(event.data.module_name)} /`) : ''}
                    ${event.data.dojo_id && event.data.module_id && event.data.challenge_id ?
                        `<a href="/${escapeHtml(event.data.dojo_id)}/${escapeHtml(event.data.module_id)}#${escapeHtml(event.data.challenge_id)}"><strong>${escapeHtml(event.data.challenge_name)}</strong></a>` :
                        `<strong>${escapeHtml(event.data.challenge_name)}</strong>`}
                `;
                break;
                
            case 'challenge_solve':
                iconHtml = '<i class="fas fa-flag-checkered fa-2x text-success"></i>';
                contentHtml = `
                    <strong><a href="/hacker/${escapeHtml(event.user_name)}">${formatUserName(event)}</a></strong>
                    solved 
                    ${event.data.dojo_name ? `<a href="/dojos/${escapeHtml(event.data.dojo_id)}">${escapeHtml(event.data.dojo_name)}</a> / ` : 
                       (event.data.dojo_id ? `<a href="/dojos/${escapeHtml(event.data.dojo_id)}">${escapeHtml(event.data.dojo_id)}</a> / ` : '')}
                    ${event.data.module_name ? 
                        (event.data.dojo_id && event.data.module_id ? 
                            `<a href="/${escapeHtml(event.data.dojo_id)}/${escapeHtml(event.data.module_id)}">${escapeHtml(event.data.module_name)}</a> / ` : 
                            `${escapeHtml(event.data.module_name)} / `) : ''}
                    ${event.data.dojo_id && event.data.module_id && event.data.challenge_id ?
                        `<a href="/${escapeHtml(event.data.dojo_id)}/${escapeHtml(event.data.module_id)}#${escapeHtml(event.data.challenge_id)}"><strong>${escapeHtml(event.data.challenge_name)}</strong></a>` :
                        `<strong>${escapeHtml(event.data.challenge_name)}</strong>`}
                    ${event.data.first_blood ? ' <span class="badge bg-danger">FIRST BLOOD!</span>' : ''}
                `;
                break;
                
            case 'emoji_earned':
                iconHtml = `<span style="font-size: 2em;">${event.data.emoji}</span>`;
                contentHtml = `
                    <strong><a href="/hacker/${escapeHtml(event.user_name)}">${formatUserName(event)}</a></strong>
                    earned the <strong>${event.data.emoji}</strong> emoji!
                    ${event.data.dojo_name ? 
                        `<br><small class="text-muted">Completed <a href="/dojos/${escapeHtml(event.data.dojo_id)}">${escapeHtml(event.data.dojo_name)}</a></small>` :
                        (event.data.dojo_id ? 
                            `<br><small class="text-muted">Completed <a href="/dojos/${escapeHtml(event.data.dojo_id)}">${escapeHtml(event.data.dojo_id)}</a></small>` :
                            `<br><small class="text-muted">${escapeHtml(event.data.reason)}</small>`)}
                `;
                break;
                
            case 'belt_earned':
                iconHtml = '<i class="fas fa-award fa-2x text-warning"></i>';
                contentHtml = `
                    <strong><a href="/hacker/${escapeHtml(event.user_name)}">${formatUserName(event)}</a></strong>
                    earned their <strong>${escapeHtml(event.data.belt_name)}</strong>!
                    ${event.data.dojo_name ? 
                        `<br><small class="text-muted">Completed <a href="/dojos/${escapeHtml(event.data.dojo_id)}">${escapeHtml(event.data.dojo_name)}</a></small>` : 
                        (event.data.dojo_id ? 
                            `<br><small class="text-muted">Completed <a href="/dojos/${escapeHtml(event.data.dojo_id)}">${escapeHtml(event.data.dojo_id)}</a></small>` : '')}
                `;
                break;
                
            case 'dojo_update':
                iconHtml = '<i class="fas fa-sync-alt fa-2x text-info"></i>';
                contentHtml = `
                    <strong><a href="/hacker/${escapeHtml(event.user_name)}">${formatUserName(event)}</a></strong>
                    updated <a href="/dojos/${escapeHtml(event.data.dojo_id)}">${escapeHtml(event.data.dojo_name || event.data.dojo_id)}</a>
                    <br><small class="text-muted">${escapeHtml(event.data.summary)}</small>
                `;
                break;
        }
        
        card.innerHTML = `
            <div class="card-body">
                <div class="d-flex align-items-center">
                    <div class="event-icon me-4" style="min-width: 50px;">${iconHtml}</div>
                    <div class="flex-grow-1">
                        <div class="event-content">${contentHtml}</div>
                        <small class="text-muted event-time" data-timestamp="${event.timestamp}">
                            ${formatTimestamp(event.timestamp)}
                        </small>
                    </div>
                </div>
            </div>
        `;
        
        return card;
    }
    
    function addEvent(event) {
        const eventsList = document.getElementById('events-list');
        
        if (document.querySelector(`[data-event-id="${event.id}"]`)) {
            return;
        }
        
        const emptyMessage = eventsList.parentElement.querySelector('.text-center.text-muted');
        if (emptyMessage) {
            emptyMessage.remove();
        }
        
        const card = createEventCard(event);
        eventsList.insertBefore(card, eventsList.firstChild);
        
        setTimeout(() => {
            card.style.transition = 'opacity 0.5s ease-in';
            card.style.opacity = '1';
        }, 10);
        
        const allCards = eventsList.querySelectorAll('.event-card');
        if (allCards.length > MAX_EVENTS) {
            const toRemove = Array.from(allCards).slice(MAX_EVENTS);
            toRemove.forEach(card => {
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
        if (eventSource) {
            eventSource.close();
        }
        
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
                } else if (data.type === 'heartbeat') {
                } else {
                    addEvent(data);
                }
            } catch (e) {
                console.error('Failed to parse event:', e);
            }
        };
        
        eventSource.onerror = (error) => {
            eventSource.close();
            
            reconnectAttempts++;
            
            if (reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
                updateConnectionStatus('error', 'Connection lost. Please refresh the page.');
            } else {
                updateConnectionStatus('error', `Connection lost. Reconnecting in ${RECONNECT_DELAY / 1000} seconds...`);
                setTimeout(connectSSE, RECONNECT_DELAY);
            }
        };
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
        if (eventSource) {
            eventSource.close();
        }
    });
})();