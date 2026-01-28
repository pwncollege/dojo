(function() {
    const MAX_EVENTS = 50;
    let eventSource = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;
    const RECONNECT_DELAY = 3000;
    
    const EVENT_TEMPLATES = {
        container_start: `
            <div class="event-card card mb-3 bg-dark text-white border-secondary">
                <div class="card-body">
                    <div class="d-flex align-items-center">
                        <div class="event-icon me-4" style="min-width: 50px;">
                            <i class="fas fa-play-circle fa-2x text-primary"></i>
                        </div>
                        <div class="flex-grow-1">
                            <div class="event-content">
                                <span class="event-user"></span>
                                <span> started a </span>
                                <span class="event-mode badge"></span>
                                <span> container for </span>
                                <span class="event-location"></span>
                            </div>
                            <small class="text-muted event-time"></small>
                        </div>
                    </div>
                </div>
            </div>`,
        
        challenge_solve: `
            <div class="event-card card mb-3 bg-dark text-white border-secondary">
                <div class="card-body">
                    <div class="d-flex align-items-center">
                        <div class="event-icon me-4" style="min-width: 50px;">
                            <i class="fas fa-flag-checkered fa-2x text-success"></i>
                        </div>
                        <div class="flex-grow-1">
                            <div class="event-content">
                                <span class="event-user"></span>
                                <span> solved </span>
                                <span class="event-location"></span>
                                <span class="event-first-blood"></span>
                            </div>
                            <small class="text-muted event-time"></small>
                        </div>
                    </div>
                </div>
            </div>`,
        
        emoji_earned: `
            <div class="event-card card mb-3 bg-dark text-white border-secondary">
                <div class="card-body">
                    <div class="d-flex align-items-center">
                        <div class="event-icon me-4" style="min-width: 50px;">
                            <span class="event-emoji-icon" style="font-size: 2em;"></span>
                        </div>
                        <div class="flex-grow-1">
                            <div class="event-content">
                                <span class="event-user"></span>
                                <span> earned the </span>
                                <strong class="event-emoji"></strong>
                                <span> emoji!</span>
                                <span class="event-emoji-detail"></span>
                            </div>
                            <small class="text-muted event-time"></small>
                        </div>
                    </div>
                </div>
            </div>`,
        
        belt_earned: `
            <div class="event-card card mb-3 bg-dark text-white border-secondary">
                <div class="card-body">
                    <div class="d-flex align-items-center">
                        <div class="event-icon me-4" style="min-width: 50px;">
                            <i class="fas fa-award fa-2x text-warning"></i>
                        </div>
                        <div class="flex-grow-1">
                            <div class="event-content">
                                <span class="event-user"></span>
                                <span> earned their </span>
                                <strong class="event-belt-name"></strong>
                                <span>!</span>
                                <span class="event-belt-detail"></span>
                            </div>
                            <small class="text-muted event-time"></small>
                        </div>
                    </div>
                </div>
            </div>`,
        
        dojo_update: `
            <div class="event-card card mb-3 bg-dark text-white border-secondary">
                <div class="card-body">
                    <div class="d-flex align-items-center">
                        <div class="event-icon me-4" style="min-width: 50px;">
                            <i class="fas fa-sync-alt fa-2x text-info"></i>
                        </div>
                        <div class="flex-grow-1">
                            <div class="event-content">
                                <span class="event-user"></span>
                                <span> updated </span>
                                <a class="event-dojo-link" href="#"></a>
                                <span class="event-update-detail"></span>
                            </div>
                            <small class="text-muted event-time"></small>
                        </div>
                    </div>
                </div>
            </div>`
    };
    
    function formatTimestamp(timestamp) {
        return new Date(timestamp).toISOString().slice(0, 19).replace('T', ' ');
    }
    
    function createLink(href, text) {
        const link = document.createElement('a');
        link.href = href;
        link.textContent = text;
        return link;
    }
    
    function createUserElement(userName, belt, emojis) {
        const container = document.createElement('strong');
        const link = document.createElement('a');
        link.href = `/hacker/${userName}`;
        
        if (belt) {
            const img = document.createElement('img');
            img.src = `/belt/${belt}.svg`;
            img.className = 'scoreboard-belt';
            img.style.cssText = 'height: 1.5em; vertical-align: middle; margin-right: 0.25em;';
            img.title = belt.charAt(0).toUpperCase() + belt.slice(1) + ' Belt';
            link.appendChild(img);
        }
        
        const nameSpan = document.createElement('span');
        nameSpan.textContent = userName;
        link.appendChild(nameSpan);
        
        if (emojis?.length > 0) {
            emojis.slice(0, 3).forEach(emoji => {
                const span = document.createElement('span');
                span.textContent = ' ' + emoji;
                span.title = emoji;
                link.appendChild(span);
            });
            
            if (emojis.length > 3) {
                const more = document.createElement('small');
                more.className = 'text-muted';
                more.textContent = ` +${emojis.length - 3}`;
                link.appendChild(more);
            }
        }
        
        container.appendChild(link);
        return container;
    }
    
    function createLocationElement(data) {
        const fragment = document.createDocumentFragment();
        
        if (data.dojo_name || data.dojo_id) {
            const dojoLink = createLink(`/dojos/${data.dojo_id}`, data.dojo_name || data.dojo_id);
            fragment.appendChild(dojoLink);
            fragment.appendChild(document.createTextNode(' / '));
        }
        
        if (data.module_name) {
            if (data.dojo_id && data.module_id) {
                const moduleLink = createLink(`/${data.dojo_id}/${data.module_id}`, data.module_name);
                fragment.appendChild(moduleLink);
            } else {
                fragment.appendChild(document.createTextNode(data.module_name));
            }
            fragment.appendChild(document.createTextNode(' / '));
        }
        
        if (data.challenge_name) {
            const strong = document.createElement('strong');
            if (data.dojo_id && data.module_id && data.challenge_id) {
                const challengeLink = createLink(
                    `/${data.dojo_id}/${data.module_id}#${data.challenge_id}`,
                    data.challenge_name
                );
                strong.appendChild(challengeLink);
            } else {
                strong.textContent = data.challenge_name;
            }
            fragment.appendChild(strong);
        }
        
        return fragment;
    }
    
    function createEventFromTemplate(templateHtml, event) {
        const temp = document.createElement('div');
        temp.innerHTML = templateHtml;
        const card = temp.firstElementChild;
        card.dataset.eventId = event.id;
        card.style.opacity = '0';
        
        const timeElem = card.querySelector('.event-time');
        if (timeElem) {
            timeElem.dataset.timestamp = event.timestamp;
            timeElem.textContent = formatTimestamp(event.timestamp);
        }
        
        const userElem = card.querySelector('.event-user');
        if (userElem) {
            userElem.replaceWith(createUserElement(event.user_name, event.user_belt, event.user_emojis));
        }
        
        return card;
    }
    
    const eventRenderers = {
        container_start: (event) => {
            const card = createEventFromTemplate(EVENT_TEMPLATES.container_start, event);
            
            const modeElem = card.querySelector('.event-mode');
            modeElem.classList.add(`bg-${event.data.mode === 'practice' ? 'warning' : 'primary'}`);
            modeElem.textContent = event.data.mode;
            
            const locationElem = card.querySelector('.event-location');
            locationElem.replaceWith(createLocationElement(event.data));
            
            return card;
        },
        
        challenge_solve: (event) => {
            const card = createEventFromTemplate(EVENT_TEMPLATES.challenge_solve, event);
            
            const locationElem = card.querySelector('.event-location');
            locationElem.replaceWith(createLocationElement(event.data));
            
            const firstBloodElem = card.querySelector('.event-first-blood');
            if (event.data.first_blood) {
                firstBloodElem.innerHTML = ' <span class="badge bg-danger">FIRST BLOOD!</span>';
            } else {
                firstBloodElem.remove();
            }
            
            return card;
        },
        
        emoji_earned: (event) => {
            const card = createEventFromTemplate(EVENT_TEMPLATES.emoji_earned, event);
            
            card.querySelector('.event-emoji-icon').textContent = event.data.emoji;
            card.querySelector('.event-emoji').textContent = event.data.emoji;
            
            const detailElem = card.querySelector('.event-emoji-detail');
            if (event.data.dojo_name || event.data.dojo_id) {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.appendChild(document.createTextNode('Completed '));
                small.appendChild(createLink(`/dojos/${event.data.dojo_id}`, event.data.dojo_name || event.data.dojo_id));
                
                detailElem.appendChild(br);
                detailElem.appendChild(small);
            } else if (event.data.reason) {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.textContent = event.data.reason;
                
                detailElem.appendChild(br);
                detailElem.appendChild(small);
            } else {
                detailElem.remove();
            }
            
            return card;
        },
        
        belt_earned: (event) => {
            const card = createEventFromTemplate(EVENT_TEMPLATES.belt_earned, event);
            
            card.querySelector('.event-belt-name').textContent = event.data.belt_name;
            
            const detailElem = card.querySelector('.event-belt-detail');
            if (event.data.dojo_name || event.data.dojo_id) {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.appendChild(document.createTextNode('Completed '));
                small.appendChild(createLink(`/dojos/${event.data.dojo_id}`, event.data.dojo_name || event.data.dojo_id));
                
                detailElem.appendChild(br);
                detailElem.appendChild(small);
            } else {
                detailElem.remove();
            }
            
            return card;
        },
        
        dojo_update: (event) => {
            const card = createEventFromTemplate(EVENT_TEMPLATES.dojo_update, event);
            
            const dojoLink = card.querySelector('.event-dojo-link');
            dojoLink.href = `/dojos/${event.data.dojo_id}`;
            dojoLink.textContent = event.data.dojo_name || event.data.dojo_id;
            
            const detailElem = card.querySelector('.event-update-detail');
            if (event.data.summary) {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.textContent = event.data.summary;
                
                detailElem.appendChild(br);
                detailElem.appendChild(small);
            } else {
                detailElem.remove();
            }
            
            return card;
        }
    };
    
    function createEventCard(event) {
        const renderer = eventRenderers[event.type];
        if (!renderer) {
            const card = document.createElement('div');
            card.className = 'event-card card mb-3 bg-dark text-white border-secondary';
            card.dataset.eventId = event.id;
            return card;
        }
        
        return renderer(event);
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
    
    function parseUserFilter() {
        const params = new URLSearchParams(window.location.search);
        const raw = params.get('users');
        if (!raw) return null;
        const ids = raw.split(',').map(value => value.trim()).filter(Boolean);
        return ids.length ? new Set(ids) : null;
    }
    
    function shouldIncludeEvent(event, allowedUserIds) {
        if (!allowedUserIds) return true;
        return allowedUserIds.has(String(event.user_id));
    }
    
    function connectSSE(allowedUserIds) {
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
                } else if (data.type !== 'heartbeat' && shouldIncludeEvent(data, allowedUserIds)) {
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
        const allowedUserIds = parseUserFilter();
        if (allowedUserIds) {
            document.querySelectorAll('.event-card').forEach(card => {
                const userId = card.dataset.userId;
                if (!userId || !allowedUserIds.has(userId)) {
                    card.remove();
                }
            });
        }
        updateTimestamps();
        setInterval(updateTimestamps, 60000);
        connectSSE(allowedUserIds);
        
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && eventSource) {
                eventSource.close();
            } else if (!document.hidden && (!eventSource || eventSource.readyState === EventSource.CLOSED)) {
                connectSSE(allowedUserIds);
            }
        });
    });
    
    window.addEventListener('beforeunload', () => {
        if (eventSource) eventSource.close();
    });
})();
