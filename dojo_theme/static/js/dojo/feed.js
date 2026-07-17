(function() {
    const MAX_EVENTS = 50;
    let eventSource = null;
    let reconnectTimer = null;
    let reconnectAttempts = 0;
    let connectionGeneration = 0;
    let isUnloading = false;
    let lastEventCursor = '0-0';
    let lastLegacyFeedCursor = '0.0';
    const MAX_RECONNECT_ATTEMPTS = 10;
    const RECONNECT_DELAY = 3000;
    const MAX_REDIS_STREAM_ID_COMPONENT = 18446744073709551615n;
    
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
                                <span class="event-dojo"></span>
                                <span class="event-update-detail"></span>
                            </div>
                            <small class="text-muted event-time"></small>
                        </div>
                    </div>
                </div>
            </div>`
    };
    
    function formatTimestamp(timestamp) {
        const date = new Date(timestamp);
        return Number.isNaN(date.getTime())
            ? ''
            : date.toISOString().slice(0, 19).replace('T', ' ');
    }
    
    function createLink(href, text) {
        const link = document.createElement('a');
        link.href = href;
        link.textContent = text;
        return link;
    }

    function encodeUrlComponent(value) {
        return encodeURIComponent(String(value)).replace(/[!'()*]/g, character =>
            `%${character.charCodeAt(0).toString(16).toUpperCase()}`
        );
    }

    function buildInternalUrl(...segments) {
        const urlRoot = (init.urlRoot || '').replace(/\/+$/, '');
        return `${urlRoot}/${segments.map(encodeUrlComponent).join('/')}`;
    }

    function buildDojoUrl(dojoId, moduleId, challengeReferenceId) {
        const segments = [dojoId];
        if (moduleId !== undefined && moduleId !== null) segments.push(moduleId);
        if (challengeReferenceId !== undefined && challengeReferenceId !== null) segments.push(challengeReferenceId);
        return buildInternalUrl(...segments);
    }

    function isValidUserId(userId) {
        return Number.isInteger(userId) && userId >= 1 && userId <= Number.MAX_SAFE_INTEGER;
    }

    function isCanonicalDojoReference(value) {
        return typeof value === 'string' && /^[a-z0-9-]{1,32}(?:~[0-9a-f]{8})?$/.test(value);
    }

    function isCanonicalContentId(value) {
        return typeof value === 'string' && /^[a-z0-9-]{1,32}$/.test(value);
    }

    function isFeedCursor(value) {
        return (
            typeof value === 'string'
            && /^[0-9]{1,20}-[0-9]{1,20}$/.test(value)
            && value.split('-').every(
                component => BigInt(component) <= MAX_REDIS_STREAM_ID_COMPONENT
            )
        );
    }

    function compareFeedCursors(left, right) {
        const [leftMilliseconds, leftSequence] = left.split('-').map(BigInt);
        const [rightMilliseconds, rightSequence] = right.split('-').map(BigInt);
        if (leftMilliseconds !== rightMilliseconds) {
            return leftMilliseconds < rightMilliseconds ? -1 : 1;
        }
        if (leftSequence === rightSequence) return 0;
        return leftSequence < rightSequence ? -1 : 1;
    }

    function updateFeedCursor(value) {
        if (
            isFeedCursor(value)
            && compareFeedCursors(value, lastEventCursor) >= 0
        ) {
            lastEventCursor = value;
        }
    }

    function updateLegacyFeedCursor(value) {
        if (typeof value !== 'string' || value.length < 1 || value.length > 64) {
            return;
        }
        const score = Number(value);
        if (
            Number.isFinite(score)
            && score >= 0
            && score >= Number(lastLegacyFeedCursor)
        ) {
            lastLegacyFeedCursor = value;
        }
    }

    function createUserElement(userId, userName, belt, emojis) {
        const container = document.createElement('strong');
        const content = isValidUserId(userId) ? createLink(buildInternalUrl('hacker', userId), '') : container;
        
        if (typeof belt === 'string' && belt) {
            const img = document.createElement('img');
            img.src = buildInternalUrl('belt', `${belt}.svg`);
            img.className = 'scoreboard-belt';
            img.style.cssText = 'height: 1.5em; vertical-align: middle; margin-right: 0.25em;';
            img.title = belt.charAt(0).toUpperCase() + belt.slice(1) + ' Belt';
            content.appendChild(img);
        }
        
        const nameSpan = document.createElement('span');
        nameSpan.textContent = userName || '';
        content.appendChild(nameSpan);
        
        if (Array.isArray(emojis) && emojis.length > 0) {
            emojis.slice(0, 3).forEach(emoji => {
                const span = document.createElement('span');
                span.textContent = ' ' + emoji;
                span.title = emoji;
                content.appendChild(span);
            });
            
            if (emojis.length > 3) {
                const more = document.createElement('small');
                more.className = 'text-muted';
                more.textContent = ` +${emojis.length - 3}`;
                content.appendChild(more);
            }
        }
        
        if (content !== container) container.appendChild(content);
        return container;
    }

    function createDojoElement(data) {
        const label = data.dojo_label;
        if (typeof label !== 'string') return document.createTextNode('');
        if (!isCanonicalDojoReference(data.dojo_path_id)) return document.createTextNode(label);
        return createLink(buildDojoUrl(data.dojo_path_id), label);
    }
    
    function createLocationElement(data) {
        const fragment = document.createDocumentFragment();
        
        if (typeof data.dojo_label === 'string') {
            fragment.appendChild(createDojoElement(data));
            fragment.appendChild(document.createTextNode(' / '));
        }
        
        if (typeof data.module_label === 'string') {
            if (
                isCanonicalDojoReference(data.dojo_path_id)
                && isCanonicalContentId(data.module_path_id)
            ) {
                const moduleLink = createLink(
                    buildDojoUrl(data.dojo_path_id, data.module_path_id),
                    data.module_label
                );
                fragment.appendChild(moduleLink);
            } else {
                fragment.appendChild(document.createTextNode(data.module_label));
            }
            fragment.appendChild(document.createTextNode(' / '));
        }
        
        if (typeof data.challenge_label === 'string') {
            const strong = document.createElement('strong');
            if (
                isCanonicalDojoReference(data.dojo_path_id)
                && isCanonicalContentId(data.module_path_id)
                && isCanonicalContentId(data.challenge_path_id)
            ) {
                const challengeLink = createLink(
                    buildDojoUrl(data.dojo_path_id, data.module_path_id, data.challenge_path_id),
                    data.challenge_label
                );
                strong.appendChild(challengeLink);
            } else {
                strong.textContent = data.challenge_label;
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
        card.dataset.feedScore = event.feed_score;
        card.dataset.userId = isValidUserId(event.user_profile_id)
            ? String(event.user_profile_id)
            : '';
        card.style.opacity = '0';
        
        const timeElem = card.querySelector('.event-time');
        if (timeElem) {
            timeElem.dataset.timestamp = event.timestamp;
            timeElem.textContent = formatTimestamp(event.timestamp);
        }
        
        const userElem = card.querySelector('.event-user');
        if (userElem) {
            userElem.replaceWith(createUserElement(
                event.user_profile_id,
                event.user_name,
                event.user_belt,
                event.user_emojis
            ));
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
            if (typeof event.data.dojo_label === 'string') {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.appendChild(document.createTextNode('Completed '));
                small.appendChild(createDojoElement(event.data));
                
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
            if (typeof event.data.dojo_label === 'string') {
                const br = document.createElement('br');
                const small = document.createElement('small');
                small.className = 'text-muted';
                small.appendChild(document.createTextNode('Completed '));
                small.appendChild(createDojoElement(event.data));
                
                detailElem.appendChild(br);
                detailElem.appendChild(small);
            } else {
                detailElem.remove();
            }
            
            return card;
        },
        
        dojo_update: (event) => {
            const card = createEventFromTemplate(EVENT_TEMPLATES.dojo_update, event);
            
            const dojoElem = card.querySelector('.event-dojo');
            dojoElem.replaceWith(createDojoElement(event.data));
            
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
            card.dataset.feedScore = event.feed_score;
            return card;
        }
        
        return renderer(event);
    }
    
    function addEvent(event) {
        const eventsList = document.getElementById('events-list');
        const duplicate = Array.from(document.querySelectorAll('[data-event-id]'))
            .some(card => card.dataset.eventId === event.id);
        if (duplicate) return;
        
        const emptyMessage = eventsList.parentElement.querySelector('.text-center.text-muted');
        if (emptyMessage) emptyMessage.remove();
        
        const card = createEventCard(event);
        const feedScore = Number(event.feed_score);
        const insertionPoint = Array.from(
            eventsList.querySelectorAll('.event-card')
        ).find(existingCard => {
            const existingScore = Number(existingCard.dataset.feedScore);
            return Number.isFinite(existingScore) && existingScore < feedScore;
        });
        eventsList.insertBefore(card, insertionPoint || null);
        
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
        return isValidUserId(event.user_profile_id)
            && allowedUserIds.has(String(event.user_profile_id));
    }

    function cancelReconnect() {
        if (reconnectTimer === null) return;
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }

    function disconnectSSE() {
        cancelReconnect();
        connectionGeneration += 1;
        const source = eventSource;
        eventSource = null;
        if (source) source.close();
    }

    function isCurrentSource(source, generation) {
        return eventSource === source && connectionGeneration === generation;
    }
    
    function connectSSE(allowedUserIds) {
        if (isUnloading || document.hidden) return;
        cancelReconnect();
        const previousSource = eventSource;
        eventSource = null;
        const generation = ++connectionGeneration;
        if (previousSource) previousSource.close();
        
        updateConnectionStatus('connecting', 'Connecting to live feed...');
        const streamUrl = buildInternalUrl('pwncollege_api', 'v1', 'feed', 'stream');
        const source = new EventSource(
            `${streamUrl}?cursor=${encodeURIComponent(lastEventCursor)}`
            + `&legacy_cursor=${encodeURIComponent(lastLegacyFeedCursor)}`
        );
        eventSource = source;
        
        source.onopen = () => {
            if (!isCurrentSource(source, generation) || isUnloading || document.hidden) return;
            reconnectAttempts = 0;
            updateConnectionStatus('connected', '');
        };
        
        source.onmessage = (event) => {
            if (!isCurrentSource(source, generation) || isUnloading || document.hidden) return;
            updateFeedCursor(event.lastEventId);
            try {
                const data = JSON.parse(event.data);
                updateFeedCursor(data.cursor);
                updateLegacyFeedCursor(data.legacy_cursor);
                if (data.type === 'connected') {
                    updateConnectionStatus('connected', '');
                } else if (data.type !== 'heartbeat' && shouldIncludeEvent(data, allowedUserIds)) {
                    addEvent(data);
                }
            } catch (e) {
                console.error('Failed to parse event:', e);
            }
        };
        
        source.onerror = () => {
            if (!isCurrentSource(source, generation)) return;
            source.close();
            eventSource = null;
            const reconnectGeneration = ++connectionGeneration;
            if (isUnloading || document.hidden) return;
            if (++reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
                updateConnectionStatus('error', 'Connection lost. Please refresh the page.');
            } else {
                updateConnectionStatus('error', `Connection lost. Reconnecting in ${RECONNECT_DELAY / 1000} seconds...`);
                const timer = setTimeout(() => {
                    if (reconnectTimer !== timer) return;
                    reconnectTimer = null;
                    if (
                        isUnloading
                        || document.hidden
                        || connectionGeneration !== reconnectGeneration
                        || eventSource
                    ) return;
                    connectSSE(allowedUserIds);
                }, RECONNECT_DELAY);
                reconnectTimer = timer;
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
        const eventsList = document.getElementById('events-list');
        updateFeedCursor(eventsList.dataset.feedCursor);
        updateLegacyFeedCursor(eventsList.dataset.legacyFeedCursor);
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
            if (document.hidden) {
                disconnectSSE();
            } else if (
                !isUnloading
                && reconnectTimer === null
                && (!eventSource || eventSource.readyState === EventSource.CLOSED)
            ) {
                connectSSE(allowedUserIds);
            }
        });
    });
    
    window.addEventListener('beforeunload', () => {
        isUnloading = true;
        disconnectSSE();
    });
})();
