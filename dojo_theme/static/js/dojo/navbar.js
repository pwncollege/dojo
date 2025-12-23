const broadcast = new BroadcastChannel('broadcast');

broadcast.onmessage = (event) => {
    if (event.data.msg === 'New challenge started') {
        if (window.location.pathname === '/workspace/code') {
            window.location.reload();
        }
        else if (window.location.pathname === '/workspace/desktop') {
            get_and_set_iframe_url()
        }
    }
};
function get_and_set_iframe_url() {
    // check if the window location pathname starts with /workspace/ and set the rest of the path as an variable service
    const service = window.location.pathname.startsWith('/workspace/') ? window.location.pathname.substring(11) : '';
    fetch("/pwncollege_api/v1/workspace?service=" + service)
        .then(response => response.json())
        .then(data => {
            if (data.active) {
                const iframe = $("#workspace_iframe")[0];
                if (iframe.src !== window.location.origin + data.iframe_src) {
                    const url = new URL(data.iframe_src);
                    if (data.setPort) {
                        url.port = window.location.port;
                    }

                    iframe.src = url.toString();
                }
            }
        });
}

$(() => {
    $("#show_description").click((event) =>{
        $("#dropdown-description").toggle();
        event.stopPropagation();
    });
    $("#dropdown-description").click((event) =>{
        event.stopPropagation();
    });
  $(".close-link").on("click", () => {
    $(".navbar")
      .addClass("navbar-hiding")
      .one("animationend webkitAnimationEnd oAnimationEnd MSAnimationEnd", () => {
        $(".navbar").removeClass("navbar-hiding").addClass("navbar-hidden");
        $("main").addClass("main-navbar-hidden");
        $(".navbar-pulldown").addClass("navbar-pulldown-shown");
      });
  });
  $(".navbar-pulldown").on("click", () => {
    $(".navbar")
      .removeClass("navbar-hiding")
      .removeClass("navbar-hidden");
    $("main").removeClass("main-navbar-hidden");
    $(".navbar-pulldown").removeClass("navbar-pulldown-shown");
  });
});


document.addEventListener('DOMContentLoaded', function () {
    const searchNavItem = document.querySelector('a.nav-link[href="#"] i.fa-search')?.closest('a');
    if (searchNavItem) {
        searchNavItem.addEventListener('click', function (e) {
        e.preventDefault();
        $('#searchModal').modal('show').on('shown.bs.modal', function () {
            document.getElementById('searchInput').focus();
            });
        });
    }

    document.getElementById('searchCloseBtn')?.addEventListener('click', () => {
        $('#searchModal').modal('hide');
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
            $('#searchModal').modal('hide');
        }
    });
});

$('#searchModal').on('hidden.bs.modal', function () {
    document.getElementById('searchInput').value = '';
    document.getElementById('searchResults').innerHTML = '';
    clearNavigationState();
});

const input = document.getElementById("searchInput");
const resultsEl = document.getElementById("searchResults");

let activeIndex = -1;
let resultItems = [];
let suppressScroll = false;

function renderSkeleton(count = 3) {
    resultsEl.innerHTML = "";
    for (let i = 0; i < count; i++) {
        const skeleton = document.createElement("div");
        skeleton.className = "bg-secondary rounded mb-2";
        skeleton.style.height = "1.25rem";
        skeleton.style.opacity = "0.3";
        skeleton.classList.add("skeleton-loader");
        resultsEl.appendChild(skeleton);
    }
}

function resetActiveResult() {
    resultItems.forEach((el, i) => {
        if (i === activeIndex) {
            el.style.backgroundColor = "#b7b7b7";
            el.style.borderRadius = "5px";

            if (!suppressScroll) {
                el.scrollIntoView({
                    block: "center",
                    behavior: "smooth"
                });
            }
        } else {
            el.style.backgroundColor = "";
            el.style.borderRadius = "";
        }
    });
}

document.addEventListener("mousemove", () => {
    lastInputMethod = "mouse";
});

function clearNavigationState() {
    activeIndex = -1;
    resultItems = [];
}

document.addEventListener("keydown", function (e) {
    lastInputMethod = "keyboard";

    if (document.activeElement !== input) return;

    if (e.key === "ArrowDown") {
        e.preventDefault();
        if (activeIndex < resultItems.length - 1) {
            activeIndex++;
            resetActiveResult();
        }
    } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (activeIndex > 0) {
            activeIndex--;
            resetActiveResult();
        }
    } else if (e.key === "Enter") {
        e.preventDefault();
        if (activeIndex >= 0 && resultItems[activeIndex]) {
            const link = resultItems[activeIndex].querySelector("a");
            if (link) window.location.href = link.href;
        }
    }
});


function renderSkeleton(count = 3) {
    resultsEl.innerHTML = "";
    for (let i = 0; i < count; i++) {
      const skeleton = document.createElement("div");
      skeleton.className = "bg-secondary rounded mb-2";
      skeleton.style.height = "1.25rem";
      skeleton.style.opacity = "0.3";
      skeleton.classList.add("skeleton-loader");
      resultsEl.appendChild(skeleton);
    }
}

const debounce = (fn, delay) => {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
};
  
const handleInput = () => {
    const query = input.value.trim();
    if (query.length < 2) {
        resultsEl.innerHTML = "";
        clearNavigationState();
        return;
    }

    renderSkeleton()

    fetch(`/pwncollege_api/v1/search?q=${encodeURIComponent(query)}`)
        .then(res => res.json())
        .then(data => {
        resultsEl.innerHTML = "";
        clearNavigationState();

        if (!data.success) return;

        const { dojos, modules, challenges } = data.results;

        if ((!dojos || !dojos.length) && (!modules || !modules.length) && (!challenges || !challenges.length)) {
            const noResult = document.createElement("div");
            noResult.className = "text-light mt-2";
            noResult.textContent = "No results found";
            resultsEl.appendChild(noResult);
            return;
        }

        const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

        const buildSnippet = (text, query, context = 40) => {
            if (!text) {
                return null;
            }

            const lowerText = text.toLowerCase();
            const lowerQuery = query.toLowerCase();
            const index = lowerText.indexOf(lowerQuery);
            if (index === -1) {
                return null;
            }

            const start = Math.max(index - context, 0);
            const end = Math.min(index + query.length + context, text.length);
            const snippetText = text.slice(start, end);
            const snippet = document.createElement("div");
            snippet.className = "text-muted small";

            if (start > 0) {
                snippet.appendChild(document.createTextNode("…"));
            }

            const pattern = new RegExp(escapeRegExp(query), "gi");
            let lastIndex = 0;
            snippetText.replace(pattern, (match, offset) => {
                if (offset > lastIndex) {
                    snippet.appendChild(document.createTextNode(snippetText.slice(lastIndex, offset)));
                }
                const highlight = document.createElement("b");
                highlight.style.fontWeight = "600";
                highlight.style.color = "#f1c40f";
                highlight.textContent = match;
                snippet.appendChild(highlight);
                lastIndex = offset + match.length;
                return match;
            });

            if (lastIndex < snippetText.length) {
                snippet.appendChild(document.createTextNode(snippetText.slice(lastIndex)));
            }

            if (end < text.length) {
                snippet.appendChild(document.createTextNode("…"));
            }

            return snippet;
        };

        const renderItem = (text, url, description = null) => {
            const container = document.createElement("div");
            container.className = "d-block py-1";
        
            const link = document.createElement("a");
            link.href = url;
            link.className = "text-light";
            link.textContent = text;
            container.appendChild(link);
        
            const snippet = buildSnippet(description, query);
            if (snippet && !text.toLowerCase().includes(query.toLowerCase())) {
                container.appendChild(snippet);
            }
        
            container.addEventListener("mouseenter", () => {
                if (lastInputMethod !== "mouse") return;
                suppressScroll = true;
                activeIndex = resultItems.indexOf(container);
                resetActiveResult();
                suppressScroll = false;
            });
        
            return container;
        };
        

        const renderSection = (label, items) => {
            const header = document.createElement("div");
            header.className = "text-secondary mt-3 mb-1 text-uppercase small font-weight-bold";
            header.textContent = label;
            resultsEl.appendChild(header);
            items.forEach(item => {
                resultsEl.appendChild(item);
                item.style.padding = "5px 10px";
                resultItems.push(item); 
            });
        };

        const dojoItems = data.results.dojos.map(d => renderItem(d.name, d.link, d.description));
        const moduleItems = data.results.modules.map(m =>
            renderItem(`${m.dojo.name} / ${m.name}`, m.link, m.description)
        );
        const challengeItems = data.results.challenges.map(c =>
            renderItem(`${c.dojo.name} / ${c.module.name} / ${c.name}`, c.link, c.description)
        );

        if (dojoItems.length) renderSection("Dojos", dojoItems);
        if (moduleItems.length) renderSection("Modules", moduleItems);
        if (challengeItems.length) renderSection("Challenges", challengeItems);
        });
};
  
input.addEventListener("input", debounce(handleInput, 200));
