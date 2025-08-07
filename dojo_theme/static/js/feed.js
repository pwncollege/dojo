(function() {
    const MAX_EVENTS = 50;
    let eventSource = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;
    const RECONNECT_DELAY = 3000;
    
    function formatTimestamp(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now - date;
        
        if (diff < 60000) {
            return 'just now';
        } else if (diff < 3600000) {
            const minutes = Math.floor(diff / 60000);
            return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
        } else if (diff < 86400000) {
            const hours = Math.floor(diff / 3600000);
            return `${hours} hour${hours > 1 ? 's' : ''} ago`;
        } else {
            const days = Math.floor(diff / 86400000);
            return `${days} day${days > 1 ? 's' : ''} ago`;
        }
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
        card.className = 'event-card card mb-3';
        card.dataset.eventId = event.id;
        card.style.opacity = '0';
        
        let iconHtml = '';
        let contentHtml = '';
        
        switch(event.type) {
            case 'container_start':
                iconHtml = '<i class="fas fa-play-circle fa-2x text-primary"></i>';
                const modeClass = event.data.mode === 'practice' ? 'warning' : 'primary';
                contentHtml = `
                    <strong><a href="/users/${event.user_id}">${event.user_name}</a></strong>
                    started a container in 
                    <span class="badge bg-${modeClass}">${event.data.mode} mode</span>
                    for <strong>${event.data.challenge_name}</strong>
                    ${event.data.dojo_name ? `in <a href="/dojos/${event.data.dojo_id}">${event.data.dojo_name}</a>` : ''}
                `;
                break;
                
            case 'challenge_solve':
                iconHtml = '<i class="fas fa-flag-checkered fa-2x text-success"></i>';
                contentHtml = `
                    <strong><a href="/users/${event.user_id}">${event.user_name}</a></strong>
                    solved <strong>${event.data.challenge_name}</strong>
                    ${event.data.first_blood ? '<span class="badge bg-danger">FIRST BLOOD!</span>' : ''}
                    for <strong>${event.data.points}</strong> points
                    ${event.data.dojo_name ? `in <a href="/dojos/${event.data.dojo_id}">${event.data.dojo_name}</a>` : ''}
                `;
                break;
                
            case 'emoji_earned':
                iconHtml = `<span style="font-size: 2em;">${event.data.emoji}</span>`;
                contentHtml = `
                    <strong><a href="/users/${event.user_id}">${event.user_name}</a></strong>
                    earned the <strong>${event.data.emoji} ${event.data.emoji_name}</strong> emoji!
                    <br><small class="text-muted">${event.data.reason}</small>
                `;
                break;
                
            case 'belt_earned':
                iconHtml = '<i class="fas fa-award fa-2x text-warning"></i>';
                contentHtml = `
                    <strong><a href="/users/${event.user_id}">${event.user_name}</a></strong>
                    earned their <strong>${event.data.belt_name}</strong>!
                    ${event.data.dojo_name ? `<br><small class="text-muted">Completed <a href="/dojos/${event.data.dojo_id}">${event.data.dojo_name}</a></small>` : ''}
                `;
                break;
                
            case 'dojo_update':
                iconHtml = '<i class="fas fa-sync-alt fa-2x text-info"></i>';
                contentHtml = `
                    <strong><a href="/users/${event.user_id}">${event.user_name}</a></strong>
                    updated <a href="/dojos/${event.data.dojo_id}">${event.data.dojo_name}</a>
                    <br><small class="text-muted">${event.data.summary}</small>
                `;
                break;
        }
        
        card.innerHTML = `
            <div class="card-body">
                <div class="d-flex align-items-start">
                    <div class="event-icon me-3">${iconHtml}</div>
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
            statusDiv.className = `alert ${status === 'error' ? 'alert-danger' : 'alert-info'} text-center mb-3`;
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