(function() {
    const MAX_EVENTS = 50;
    let eventSource = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;
    const RECONNECT_DELAY = 3000;
    
    function formatTimestamp(timestamp) {
        return new Date(timestamp).toISOString().slice(0, 19).replace('T', ' ');
    }
    
    function createLink(href, text) {
        const link = document.createElement('a');
        link.href = href;
        link.textContent = text;
        return link;
    }
    
    function createBadge(text, colorClass) {
        const badge = document.createElement('span');
        badge.className = `badge bg-${colorClass}`;
        badge.textContent = text;
        return badge;
    }
    
    function createBeltImage(belt) {
        const img = document.createElement('img');
        img.src = `/belt/${belt}.svg`;
        img.className = 'scoreboard-belt';
        img.style.cssText = 'height: 1.5em; vertical-align: middle; margin-right: 0.25em;';
        img.title = belt.charAt(0).toUpperCase() + belt.slice(1) + ' Belt';
        return img;
    }
    
    function createUserElement(event) {
        const strong = document.createElement('strong');
        const userLink = createLink(`/hacker/${event.user_name}`, '');
        
        if (event.user_belt) {
            userLink.appendChild(createBeltImage(event.user_belt));
        }
        
        const nameSpan = document.createElement('span');
        nameSpan.textContent = event.user_name;
        userLink.appendChild(nameSpan);
        
        if (event.user_emojis?.length > 0) {
            event.user_emojis.slice(0, 3).forEach(emoji => {
                const emojiSpan = document.createElement('span');
                emojiSpan.textContent = ' ' + emoji;
                emojiSpan.title = emoji;
                userLink.appendChild(emojiSpan);
            });
            
            if (event.user_emojis.length > 3) {
                const moreSpan = document.createElement('small');
                moreSpan.className = 'text-muted';
                moreSpan.textContent = ` +${event.user_emojis.length - 3}`;
                userLink.appendChild(moreSpan);
            }
        }
        
        strong.appendChild(userLink);
        return strong;
    }
    
    function createDojoModuleChallengeElement(data) {
        const fragment = document.createDocumentFragment();
        
        if (data.dojo_name || data.dojo_id) {
            fragment.appendChild(createLink(`/dojos/${data.dojo_id}`, data.dojo_name || data.dojo_id));
            fragment.appendChild(document.createTextNode(' / '));
        }
        
        if (data.module_name) {
            if (data.dojo_id && data.module_id) {
                fragment.appendChild(createLink(`/${data.dojo_id}/${data.module_id}`, data.module_name));
            } else {
                fragment.appendChild(document.createTextNode(data.module_name));
            }
            fragment.appendChild(document.createTextNode(' / '));
        }
        
        if (data.challenge_name) {
            const challengeStrong = document.createElement('strong');
            if (data.dojo_id && data.module_id && data.challenge_id) {
                const link = createLink(`/${data.dojo_id}/${data.module_id}#${data.challenge_id}`, data.challenge_name);
                challengeStrong.appendChild(link);
            } else {
                challengeStrong.textContent = data.challenge_name;
            }
            fragment.appendChild(challengeStrong);
        }
        
        return fragment;
    }
    
    const eventRenderers = {
        container_start: (event) => {
            const content = document.createElement('div');
            content.appendChild(createUserElement(event));
            content.appendChild(document.createTextNode(' started a '));
            content.appendChild(createBadge(event.data.mode, event.data.mode === 'practice' ? 'warning' : 'primary'));
            content.appendChild(document.createTextNode(' container for '));
            content.appendChild(createDojoModuleChallengeElement(event.data));
            
            return {
                icon: '<i class="fas fa-play-circle fa-2x text-primary"></i>',
                content: content
            };
        },
        
        challenge_solve: (event) => {
            const content = document.createElement('div');
            content.appendChild(createUserElement(event));
            content.appendChild(document.createTextNode(' solved '));
            content.appendChild(createDojoModuleChallengeElement(event.data));
            
            if (event.data.first_blood) {
                content.appendChild(document.createTextNode(' '));
                content.appendChild(createBadge('FIRST BLOOD!', 'danger'));
            }
            
            return {
                icon: '<i class="fas fa-flag-checkered fa-2x text-success"></i>',
                content: content
            };
        },
        
        emoji_earned: (event) => {
            const content = document.createElement('div');
            content.appendChild(createUserElement(event));
            content.appendChild(document.createTextNode(' earned the '));
            
            const emojiStrong = document.createElement('strong');
            emojiStrong.textContent = event.data.emoji;
            content.appendChild(emojiStrong);
            content.appendChild(document.createTextNode(' emoji!'));
            
            if (event.data.dojo_name || event.data.dojo_id) {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.appendChild(document.createTextNode('Completed '));
                small.appendChild(createLink(`/dojos/${event.data.dojo_id}`, event.data.dojo_name || event.data.dojo_id));
                content.appendChild(br);
                content.appendChild(small);
            } else if (event.data.reason) {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.textContent = event.data.reason;
                content.appendChild(br);
                content.appendChild(small);
            }
            
            return {
                icon: `<span style="font-size: 2em;">${event.data.emoji}</span>`,
                content: content
            };
        },
        
        belt_earned: (event) => {
            const content = document.createElement('div');
            content.appendChild(createUserElement(event));
            content.appendChild(document.createTextNode(' earned their '));
            
            const beltStrong = document.createElement('strong');
            beltStrong.textContent = event.data.belt_name;
            content.appendChild(beltStrong);
            content.appendChild(document.createTextNode('!'));
            
            if (event.data.dojo_name || event.data.dojo_id) {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.appendChild(document.createTextNode('Completed '));
                small.appendChild(createLink(`/dojos/${event.data.dojo_id}`, event.data.dojo_name || event.data.dojo_id));
                content.appendChild(br);
                content.appendChild(small);
            }
            
            return {
                icon: '<i class="fas fa-award fa-2x text-warning"></i>',
                content: content
            };
        },
        
        dojo_update: (event) => {
            const content = document.createElement('div');
            content.appendChild(createUserElement(event));
            content.appendChild(document.createTextNode(' updated '));
            content.appendChild(createLink(`/dojos/${event.data.dojo_id}`, event.data.dojo_name || event.data.dojo_id));
            
            if (event.data.summary) {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.textContent = event.data.summary;
                content.appendChild(br);
                content.appendChild(small);
            }
            
            return {
                icon: '<i class="fas fa-sync-alt fa-2x text-info"></i>',
                content: content
            };
        }
    };
    
    function createEventCard(event) {
        const card = document.createElement('div');
        card.className = 'event-card card mb-3 bg-dark text-white border-secondary';
        card.dataset.eventId = event.id;
        card.style.opacity = '0';
        
        const renderer = eventRenderers[event.type];
        if (!renderer) return card;
        
        const {icon, content} = renderer(event);
        
        // Create structure with innerHTML (trusted HTML only)
        card.innerHTML = `
            <div class="card-body">
                <div class="d-flex align-items-center">
                    <div class="event-icon me-4" style="min-width: 50px;">${icon}</div>
                    <div class="flex-grow-1">
                        <div class="event-content"></div>
                        <small class="text-muted event-time" data-timestamp="${event.timestamp}">
                            ${formatTimestamp(event.timestamp)}
                        </small>
                    </div>
                </div>
            </div>`;
        
        // Append the content DOM element (with user data safely inserted)
        const contentDiv = card.querySelector('.event-content');
        if (content instanceof Node) {
            contentDiv.appendChild(content);
        } else {
            contentDiv.textContent = content;
        }
        
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