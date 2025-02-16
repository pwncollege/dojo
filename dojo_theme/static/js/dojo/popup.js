
const BELT_ORDER = ["white", "orange", "yellow", "green", "blue", "black"];
const BELT_MESSAGES = {
    white: "<b>You've earned your white belt!</b><br>The journey begins!",
    orange: "<b>Orange belt achieved!</b><br>Vulnerability Seeker - You know where to strike first.",
    yellow: "<b>Yellow belt unlocked!</b><br>Buffer Breaker - Exploiting memory, one byte at a time.",
    green: "<b>Green belt obtained!</b><br>Precision Hacker - No gap too small, no exploit too complex.",
    blue: "<b>Blue belt conquered!</b><br>Master of the System - You&#39;ve conquered the complexity others fear.",
    black: "<b>Black belt Mentor!</b><br> Architect of Understanding - You forge minds as sharp as your exploits."
};

document.addEventListener("DOMContentLoaded", function () {
    if (!init?.userId) return;
    
    checkUserAwards()
        .then(handleAwardPopup)
        .catch(error => console.error("Award check failed:", error));
});

function checkUserAwards() {
    const endpoint = `${CTFd.config.urlRoot}/api/v1/users/${init.userId}/awards`;
    return fetch(endpoint, {
        method: "GET",
        credentials: "same-origin",
        headers: {"Accept": "application/json"}
    }).then(res => res.json());
}

function handleAwardPopup(response) {
    if (!response?.success || !response.data?.length) return;

    const awards = response.data;

    const beltAwards = awards.filter(a => BELT_ORDER.includes(a.name)).sort(dateSort);
    const otherAwards = awards.filter(a => !BELT_ORDER.includes(a.name)).sort(dateSort);
    const latestAward = beltAwards.pop() || otherAwards.pop();
    
    const lastSeen = localStorage.getItem("lastAwardDate") || "1970-01-01";
    if (new Date(latestAward.date) <= new Date(lastSeen)) return;
    

    localStorage.setItem("lastAwardDate", latestAward.date);
    showAwardPopup(latestAward);
}

function dateSort(a, b) {
    return new Date(a.date) - new Date(b.date);
}

function showAwardPopup(award) {
    const isBelt = BELT_ORDER.includes(award.name);

    const imageContent = isBelt ? 
    `<img src = "https://pwn.college/belt/${award.name}.svg" 
        class="belt-image"
        loading="lazy">` : 
    `<div class="emoji-display">${award.name}</div>`;

    const customMessage = isBelt
        ? BELT_MESSAGES[award.name]
        : award?.description 
            ? `You've completed the ${award.description} dojo!`
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
        profileUrl: `https://pwn.college/hacker/${init.userId}`
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




