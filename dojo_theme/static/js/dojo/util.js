function copyToClipboard(event) {
    event.preventDefault();
    const text = event.currentTarget.dataset.copy;
    navigator.clipboard.writeText(text)
    .then(() => {
        const tooltip = event.currentTarget.querySelector("#tooltip");
        const original = tooltip.innerText;
        tooltip.innerText = "Copied!";
        setTimeout(() => {
            tooltip.innerText = original;
        }, 1000);
    })
}
