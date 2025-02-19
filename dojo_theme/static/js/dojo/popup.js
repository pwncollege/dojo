
const BELT_ORDER = ["white", "orange", "yellow", "green", "blue", "black"];

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
    }).then(res => res.json());
}

function handleAwardPopup(response) {
    if (!response?.success || !response.data?.length) return;

    const awards = response.data;

    const sortedAwards = awards.sort((a, b) => new Date(a.date) - new Date(b.date));
    const latestAward = sortedAwards.pop();
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
    
    const lastSeen = localStorage.getItem("lastAwardDate") || twoDaysAgo;
    if (new Date(latestAward.date) <= new Date(lastSeen)) return;

    localStorage.setItem("lastAwardDate", latestAward.date);
    showAwardPopup(latestAward);
}

function showAwardPopup(award) {
    const isBelt = BELT_ORDER.includes(award.name);

    const imageContent = isBelt ? 
    `<img src = "/belt/${award.name}.svg" 
        class="belt-image">` : 
    `<div class="emoji-display">${award.name}</div>`;

    const customMessage = isBelt
        ? `You have officially been awarded your ${award.name} belt!`
        : award?.description 
            ? `${award.description}`
            : "You have completed a dojo!";

    const popupContent = {
        header: "Congratulations!",
        body: customMessage,
        image: imageContent,
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
