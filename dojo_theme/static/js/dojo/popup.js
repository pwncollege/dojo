document.addEventListener("DOMContentLoaded", function () {
    if (!init?.userId) return;

    checkUserAwards()
        .then(handleAwardPopup)
        .catch(error => console.error("Award check failed:", error));
});

function checkUserAwards() {
    const endpoint = `/api/v1/users/${init.userId}/awards`;
    return CTFd.fetch(endpoint, {
        method: "GET",
        credentials: "same-origin",
        headers: {"Accept": "application/json"}
    }).then(response => response.json());
}

function handleAwardPopup(response) {
    if (!response?.success || !response.data?.length) return;

    const award = response.data.sort((a, b) => new Date(a.date) - new Date(b.date)).pop();

    const lastAwardDate = new Date(award.date);
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000);
    const lastPopup = new Date(localStorage.getItem("lastPopup"));

    if (lastAwardDate <= twoDaysAgo || lastAwardDate <= lastPopup) return;

    localStorage.setItem("lastPopup", lastAwardDate.toISOString());

    showAwardPopup(award);
}

function showAwardPopup(award) {
    const isBelt = Array.from(award.name).length > 1 && !award.icon;

    const image = isBelt
        ? `<img src="/belt/${award.name}.svg" class="belt-image">`
        : `<div class="emoji-display">${award.icon || award.name}</div>`;

    // For emoji awards with icon, extract dojo name from description
    let displayName = award.name;
    if (award.icon && award.description) {
        const match = award.description.match(/Awarded for completing the (.+?) dojo\./);
        displayName = match ? match[1] : award.name;
    }
    
    const message = isBelt
        ? `You have officially been awarded your ${award.name} belt!`
        : `You have officially been awarded the ${displayName} badge!`;

    const popupContent = {
        header: "Congratulations!",
        body: message,
        image: image,
        logos: {
            ninja: `${CTFd.config.urlRoot}/themes/dojo_theme/static/img/dojo/ninja.png`,
            linkedin: `${CTFd.config.urlRoot}/themes/dojo_theme/static/img/dojo/linkedin_logo.svg`,
            x: `${CTFd.config.urlRoot}/themes/dojo_theme/static/img/dojo/x_logo.svg`
        },
        profileUrl: `${window.location.protocol}//${window.location.host}/hacker/${init.userId}`
    };

    const popup = document.createElement("div");
    popup.className = "popup-overlay";
    popup.innerHTML = `
        <div class="popup-content">
            <button id="closePopup">&times;</button>
            ${popupContent.image}
            <h1>${popupContent.header}</h1>
            <p>${popupContent.body}</p>
            <img src="${popupContent.logos.ninja}" class="logo-image">
            <div class="social-share">
                <a href="https://linkedin.com/share?url=${popupContent.profileUrl}"
                    class="share-button"
                    target="_blank"
                    aria-label="Post on LinkedIn">
                    <img src="${popupContent.logos.linkedin}">
                    <span title="Post on LinkedIn"></span>Post
                </a>
                <a href="https://twitter.com/intent/tweet?url=${popupContent.profileUrl}"
                    class="share-button"
                    target="_blank"
                    aria-label="Post on X">
                    <img src="${popupContent.logos.x}">
                    <span title="Post on X"></span>Post
                </a>
            </div>
        </div>
    `;

    document.body.appendChild(popup);
    popup.querySelector("#closePopup").addEventListener("click", () => {
        popup.remove();
    });

    popup.addEventListener("click", (e) => {
        if (e.target === popup){
            popup.remove();
        }
    });
}
